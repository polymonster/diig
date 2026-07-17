// storekit 2 subscription bridge exposed to c++ via @_cdecl (see store_bridge.h)
// swift async tasks mutate a lock guarded state snapshot which the app frame
// loop polls as json via ios_store_get_state_json

import Foundation
import StoreKit
import CryptoKit
import UIKit

final class StoreBridge {
    static let shared = StoreBridge()

    private let lock = NSLock()

    // config
    private var rcApiKey = ""
    private var productIds: [String] = []
    private var appUserId = ""

    // storekit
    private var products: [Product] = []
    private var updatesTask: Task<Void, Never>? = nil

    // polled state
    private var initialized = false
    private var productsLoaded = false
    private var purchasing = false
    private var pending = false
    private var restoring = false
    private var rcSynced = false
    private var lastError = ""
    private var entitlementChecked = false
    private var entitlementActive = false
    private var entitlementProductId = ""
    private var entitlementExpiresMs: Double = 0

    private func with<T>(_ body: () -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return body()
    }

    // MARK: - lifecycle

    func initialize(rcApiKey: String, productIds: [String]) {
        let start: Bool = with {
            if initialized {
                return false
            }
            initialized = true
            self.rcApiKey = rcApiKey
            self.productIds = productIds
            return true
        }
        if !start {
            return
        }

        // observe transactions that occur outside a direct purchase call
        // (renewals, ask to buy approvals, purchases on other devices)
        updatesTask = Task.detached { [weak self] in
            for await update in Transaction.updates {
                guard let self = self else {
                    return
                }
                if case .verified(let transaction) = update {
                    await self.postToRevenueCat(jws: update.jwsRepresentation)
                    await transaction.finish()
                    await self.refreshEntitlements()
                }
            }
        }

        Task {
            await loadProducts()
            await refreshEntitlements()
        }
    }

    func setUser(_ uid: String) {
        with {
            appUserId = uid
        }
    }

    // MARK: - products

    private func loadProducts() async {
        let ids: [String] = with { productIds }
        do {
            let loaded = try await Product.products(for: ids)
            // preserve the order given in product ids
            let sorted = ids.compactMap { id in loaded.first(where: { $0.id == id }) }
            with {
                products = sorted
                productsLoaded = true
            }
        } catch {
            with {
                lastError = "failed to load products: \(error.localizedDescription)"
            }
        }
    }

    // MARK: - purchase / restore

    func purchase(productId: String) {
        let (product, busy): (Product?, Bool) = with {
            (products.first(where: { $0.id == productId }), purchasing)
        }
        if busy {
            return
        }
        guard let product = product else {
            with {
                lastError = "unknown product: \(productId)"
            }
            return
        }
        with {
            purchasing = true
            pending = false
            lastError = ""
        }
        Task {
            do {
                var options: Set<Product.PurchaseOption> = []
                if let token = appAccountToken() {
                    options.insert(.appAccountToken(token))
                }
                let result = try await product.purchase(options: options)
                switch result {
                case .success(let verification):
                    if case .verified(let transaction) = verification {
                        await postToRevenueCat(jws: verification.jwsRepresentation)
                        await transaction.finish()
                        await refreshEntitlements()
                    } else {
                        with {
                            lastError = "purchase failed verification"
                        }
                    }
                case .userCancelled:
                    break
                case .pending:
                    // ask to buy etc, completes later via Transaction.updates
                    with {
                        pending = true
                    }
                @unknown default:
                    break
                }
            } catch {
                with {
                    lastError = "purchase failed: \(error.localizedDescription)"
                }
            }
            with {
                purchasing = false
            }
        }
    }

    func restore() {
        let busy: Bool = with { restoring }
        if busy {
            return
        }
        with {
            restoring = true
            lastError = ""
        }
        Task {
            do {
                try await AppStore.sync()
                // resync anything we now hold with revenuecat
                for await result in Transaction.currentEntitlements {
                    if case .verified = result {
                        await postToRevenueCat(jws: result.jwsRepresentation)
                    }
                }
                await refreshEntitlements()
            } catch {
                with {
                    lastError = "restore failed: \(error.localizedDescription)"
                }
            }
            with {
                restoring = false
            }
        }
    }

    func manageSubscriptions() {
        Task { @MainActor in
            let scene = UIApplication.shared.connectedScenes
                .first(where: { $0.activationState == .foregroundActive }) as? UIWindowScene
            if let scene = scene {
                try? await AppStore.showManageSubscriptions(in: scene)
            } else if let url = URL(string: "https://apps.apple.com/account/subscriptions") {
                await UIApplication.shared.open(url)
            }
        }
    }

    // MARK: - entitlements

    private func refreshEntitlements() async {
        var active = false
        var productId = ""
        var expiresMs: Double = 0
        for await result in Transaction.currentEntitlements {
            if case .verified(let transaction) = result {
                if transaction.revocationDate != nil {
                    continue
                }
                if let expires = transaction.expirationDate {
                    if expires > Date() {
                        active = true
                        productId = transaction.productID
                        expiresMs = expires.timeIntervalSince1970 * 1000.0
                    }
                } else {
                    // non expiring (lifetime) purchase
                    active = true
                    productId = transaction.productID
                }
            }
        }
        with {
            entitlementChecked = true
            entitlementActive = active
            entitlementProductId = productId
            entitlementExpiresMs = expiresMs
        }
    }

    // MARK: - revenuecat

    private func postToRevenueCat(jws: String) async {
        let (key, uid): (String, String) = with { (rcApiKey, appUserId) }
        if key.isEmpty || uid.isEmpty {
            return
        }
        guard let url = URL(string: "https://api.revenuecat.com/v1/receipts") else {
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.addValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        request.addValue("ios", forHTTPHeaderField: "X-Platform")
        request.addValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "app_user_id": uid,
            "fetch_token": jws
        ]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            with {
                rcSynced = (200...299).contains(code)
                if !rcSynced {
                    lastError = "revenuecat sync failed: http \(code)"
                }
            }
        } catch {
            with {
                rcSynced = false
                lastError = "revenuecat sync failed: \(error.localizedDescription)"
            }
        }
    }

    // deterministic uuid v5 from the firebase uid so the same user maps to the
    // same appAccountToken on every device
    private func appAccountToken() -> UUID? {
        let uid: String = with { appUserId }
        if uid.isEmpty {
            return nil
        }
        // rfc 4122 dns namespace
        let namespace: [UInt8] = [
            0x6b, 0xa7, 0xb8, 0x10, 0x9d, 0xad, 0x11, 0xd1,
            0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8
        ]
        var data = Data(namespace)
        data.append(Data("diig:\(uid)".utf8))
        let digest = Insecure.SHA1.hash(data: data)
        var bytes = Array(digest.prefix(16))
        bytes[6] = (bytes[6] & 0x0f) | 0x50 // version 5
        bytes[8] = (bytes[8] & 0x3f) | 0x80 // rfc 4122 variant
        return UUID(uuid: (bytes[0], bytes[1], bytes[2], bytes[3],
                           bytes[4], bytes[5], bytes[6], bytes[7],
                           bytes[8], bytes[9], bytes[10], bytes[11],
                           bytes[12], bytes[13], bytes[14], bytes[15]))
    }

    // MARK: - polled state

    func stateJson() -> String {
        let dict: [String: Any] = with {
            var productList: [[String: Any]] = []
            for product in products {
                var period = ""
                if let sub = product.subscription {
                    switch sub.subscriptionPeriod.unit {
                    case .day: period = "day"
                    case .week: period = "week"
                    case .month: period = "month"
                    case .year: period = "year"
                    @unknown default: period = ""
                    }
                }
                productList.append([
                    "id": product.id,
                    "title": product.displayName,
                    "description": product.description,
                    "price": product.displayPrice,
                    "period": period
                ])
            }
            return [
                "initialized": initialized,
                "products_loaded": productsLoaded,
                "purchasing": purchasing,
                "pending": pending,
                "restoring": restoring,
                "rc_synced": rcSynced,
                "last_error": lastError,
                "entitlement": [
                    "checked": entitlementChecked,
                    "active": entitlementActive,
                    "product_id": entitlementProductId,
                    "expires_ms": entitlementExpiresMs
                ],
                "products": productList
            ]
        }
        guard let data = try? JSONSerialization.data(withJSONObject: dict),
              let json = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return json
    }
}

// MARK: - c interface

@_cdecl("ios_store_init")
public func ios_store_init(_ rcApiKey: UnsafePointer<CChar>?, _ productIdsCsv: UnsafePointer<CChar>?) {
    let key = rcApiKey != nil ? String(cString: rcApiKey!) : ""
    let csv = productIdsCsv != nil ? String(cString: productIdsCsv!) : ""
    let ids = csv.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    StoreBridge.shared.initialize(rcApiKey: key, productIds: ids)
}

@_cdecl("ios_store_set_user")
public func ios_store_set_user(_ appUserId: UnsafePointer<CChar>?) {
    StoreBridge.shared.setUser(appUserId != nil ? String(cString: appUserId!) : "")
}

@_cdecl("ios_store_purchase")
public func ios_store_purchase(_ productId: UnsafePointer<CChar>?) {
    guard let productId = productId else {
        return
    }
    StoreBridge.shared.purchase(productId: String(cString: productId))
}

@_cdecl("ios_store_restore")
public func ios_store_restore() {
    StoreBridge.shared.restore()
}

@_cdecl("ios_store_manage_subscriptions")
public func ios_store_manage_subscriptions() {
    StoreBridge.shared.manageSubscriptions()
}

@_cdecl("ios_store_get_state_json")
public func ios_store_get_state_json(_ buf: UnsafeMutablePointer<CChar>?, _ bufSize: UInt32) -> UInt32 {
    guard let buf = buf, bufSize > 1 else {
        return 0
    }
    let bytes = Array(StoreBridge.shared.stateJson().utf8)
    let count = min(bytes.count, Int(bufSize) - 1)
    for i in 0..<count {
        buf[i] = CChar(bitPattern: bytes[i])
    }
    buf[count] = 0
    return UInt32(count)
}
