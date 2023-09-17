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

-- Engine Project
dofile "pmtech/core/pen/project.lua"
dofile "pmtech/core/put/project.lua"
configuration{}
	includedirs{
		"."
	}

-- Example projects
-- ( project name, current script dir, )
create_app( "dig", "", script_path() )



