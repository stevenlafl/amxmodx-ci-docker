#if defined _flat_included
	#endinput
#endif
#define _flat_included

stock flat_name(out[], len)
	return copy(out, len, "flat")
