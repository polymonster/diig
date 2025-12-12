require "pmtech/third_party/pmbuild/scripts/premake-android-studio/android_studio"

dofile "pmtech/tools/premake/options.lua"
dofile "pmtech/tools/premake/globals.lua"
dofile "pmtech/tools/premake/app_template.lua"

-- Solution
solution ("diig_" .. platform_dir)
	location ("build/" .. platform_dir )
	configurations { "Debug", "Release" }
	startproject "diig"
	buildoptions { build_cmd }
	linkoptions { link_cmd }

-- android dist overrides
if platform == "android" then
	androidnamespace "pmtech.diig"
	androidappid "pmtech.diig"
	androidversioncode "4"
    androidversionname "1.0"
	androidmanifest "dist\\android\\AndroidManifest.xml"
	gradleversion "com.android.tools.build:gradle:8.2.2"
	androidsdkversion "35"
	androidndkversion "25.1.8937393"
	androidminsdkversion "21"
	gradlewrapper {
		"distributionUrl=https\\://services.gradle.org/distributions/gradle-8.6-all.zip"
	}
	androidrepositories {
		"google()",
		"mavenCentral()"
	}
	androiddependencies {
		"androidx.appcompat:appcompat:1.7.0",
		"com.google.android.material:material:1.12.0",
		"androidx.security:security-crypto:1.1.0-alpha06"
	}
	gradleproperties {
		"org.gradle.jvmargs=-Xmx4608m --add-exports=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.lang.reflect=ALL-UNNAMED --add-opens=java.base/java.io=ALL-UNNAMED --add-exports=jdk.unsupported/sun.misc=ALL-UNNAMED",
		"org.gradle.parallel=true",
		"org.gradle.daemon=true",
		"android.useAndroidX=true",
		"android.enableJetifier=true",
		"android.bundle.enableUncompressedNativeLibs=true"
	}
	assetdirs {
		"bin/android/assets",
	}
	linkoptions {
		"max-page-size=16384",
		"-Wl",
		"-z",
	}
	androiduselegacypackaging "true"
	files {
		"dist/android/res/**.*"
	}
end

-- engine
dofile "pmtech/core/pen/project.lua"

configuration{}
if platform == "ios" then
    xcodebuildsettings {
		["IPHONEOS_DEPLOYMENT_TARGET"] = 15.0,
		["SKIP_INSTALL"] = "YES"
	}
end

dofile "pmtech/core/put/project.lua"

configuration{}
if platform == "ios" then
    xcodebuildsettings {
		["IPHONEOS_DEPLOYMENT_TARGET"] = 15.0,
		["SKIP_INSTALL"] = "YES"
	}
end

-- includes for shader builds
configuration{}
	includedirs{
		"."
	}

-- app
create_app("diig", "", script_path())

-- ios dist overrides
configuration{}
if platform == "ios" then
    xcodebuildsettings {
		["ASSETCATALOG_COMPILER_APPICON_NAME"] = "AppIcon",
        ["PRODUCT_BUNDLE_IDENTIFIER"] = "com.pmtech.dig",
		["DEVELOPMENT_TEAM"] = "7C3Y39TX3G", -- personal team (Alex Dixon)
		["IPHONEOS_DEPLOYMENT_TARGET"] = 15.0,
		["SKIP_INSTALL"] = "NO"
    }

	files {
		"dist/ios/Images.xcassets"
	}

	xcodebuildresources {
		"dist/ios/Images.xcassets"
	}

	links {
		"CoreGraphics.framework"
	}

	linkoptions {
		"-ld_classic"
	}
end


