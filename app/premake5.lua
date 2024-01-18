dofile "pmtech/tools/premake/options.lua"
dofile "pmtech/tools/premake/globals.lua"
dofile "pmtech/tools/premake/app_template.lua"

-- Solution
solution ("dig" .. platform_dir)
	location ("build/" .. platform_dir )
	configurations { "Debug", "Release" }
	startproject "dig"
	buildoptions { build_cmd }
	linkoptions { link_cmd }

-- engine
dofile "pmtech/core/pen/project.lua"

configuration{}
if platform == "ios" then
    xcodebuildsettings {
		["IPHONEOS_DEPLOYMENT_TARGET"] = 15.0
	}
end

dofile "pmtech/core/put/project.lua"

configuration{}
if platform == "ios" then
    xcodebuildsettings {
		["IPHONEOS_DEPLOYMENT_TARGET"] = 15.0
	}
end

-- includes for shader builds
configuration{}
	includedirs{
		"."
	}

-- app
create_app("dig", "", script_path())

-- ios dist overrides
configuration{}
if platform == "ios" then
    xcodebuildsettings {
		["ASSETCATALOG_COMPILER_APPICON_NAME"] = "AppIcon",
        ["PRODUCT_BUNDLE_IDENTIFIER"] = "com.pmtech.dig",
		["DEVELOPMENT_TEAM"] = "7C3Y39TX3G", -- personal team (Alex Dixon)
		["IPHONEOS_DEPLOYMENT_TARGET"] = 15.0
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
end



