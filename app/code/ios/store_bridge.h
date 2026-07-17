// c interface to the ios storekit 2 subscription bridge (store_bridge.swift)
// state is polled from the app frame loop via ios_store_get_state_json, swift
// tasks update a lock guarded snapshot so no callbacks cross the language boundary

#pragma once

#if PEN_PLATFORM_IOS
extern "C"
{
    // start storekit, load products and begin observing transactions
    // rc_api_key: revenuecat public api key (may be empty to disable rc sync)
    // product_ids_csv: comma separated subscription product ids
    void            ios_store_init(const char* rc_api_key, const char* product_ids_csv);

    // set the app user id (firebase uid) used for revenuecat and appAccountToken
    void            ios_store_set_user(const char* app_user_id);

    // begin a purchase for the given product id (async, poll state for result)
    void            ios_store_purchase(const char* product_id);

    // restore previous purchases (AppStore.sync)
    void            ios_store_restore();

    // show the manage subscriptions sheet
    void            ios_store_manage_subscriptions();

    // copies a null terminated json snapshot of store state into buf,
    // returns number of bytes written (excluding null terminator)
    unsigned int    ios_store_get_state_json(char* buf, unsigned int buf_size);
}
#else
// no-op stubs so shared code can call unconditionally on other platforms
inline void         ios_store_init(const char*, const char*) {}
inline void         ios_store_set_user(const char*) {}
inline void         ios_store_purchase(const char*) {}
inline void         ios_store_restore() {}
inline void         ios_store_manage_subscriptions() {}
inline unsigned int ios_store_get_state_json(char*, unsigned int) { return 0; }
#endif
