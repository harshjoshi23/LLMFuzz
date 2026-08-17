#ifndef CY_PPCA_SHM_CONFIG_H
#define CY_PPCA_SHM_CONFIG_H

// Host-side fuzz harness configuration.
// The harness also defines these macros before including the library headers;
// these defaults exist to satisfy includes that expect this header to exist.

#ifndef CONFIG_USE_MEMORY_POOL
#define CONFIG_USE_MEMORY_POOL 1
#endif

#ifndef CONFIG_SHARED_MEM_POOL_SIZE
#define CONFIG_SHARED_MEM_POOL_SIZE 4096
#endif

#ifndef CONFIG_USE_DOUBLE_BUFFER
#define CONFIG_USE_DOUBLE_BUFFER 0
#endif

#ifndef CONFIG_USE_IPC_LOCK
#define CONFIG_USE_IPC_LOCK 0
#endif

#ifndef CONFIG_USE_MUTEX_LOCK
#define CONFIG_USE_MUTEX_LOCK 0
#endif

#ifndef CONFIG_USE_TRIPLE_BUFFER
#define CONFIG_USE_TRIPLE_BUFFER 0
#endif

#endif /* CY_PPCA_SHM_CONFIG_H */
