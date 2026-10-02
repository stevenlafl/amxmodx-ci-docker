#include <amxmodx>
#include <flat>

public plugin_init()
{
	new name[16]
	flat_name(name, charsmax(name))
	register_plugin(name, "1.0", "tests")
}
