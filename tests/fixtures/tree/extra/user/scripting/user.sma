#include <amxmodx>
#include <mylib>

public plugin_init()
{
	register_plugin("user", "1.0", "tests")
	mylib_hello(0)
}
