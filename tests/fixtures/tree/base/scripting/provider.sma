#include <amxmodx>

public plugin_init()
	register_plugin("provider", "1.0", "tests")

public plugin_natives()
{
	register_library("mylib")
	register_native("mylib_hello", "_hello")
	register_native("mylib_unused", "_unused")
}

public _hello(plugin, params)
	return get_param(1)

public _unused(plugin, params)
	return 0
