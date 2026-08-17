#ifndef CY_ASSERT_H
#define CY_ASSERT_H

// Host-side stub for ModusToolbox assert helpers.

#include <stdlib.h>

#ifndef CY_ASSERT
#define CY_ASSERT(x) do { if (!(x)) abort(); } while (0)
#endif

#ifndef CY_ASSERT_HANDLER
#define CY_ASSERT_HANDLER() abort()
#endif

#endif /* CY_ASSERT_H */
