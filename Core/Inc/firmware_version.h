/**
  ******************************************************************************
  * @file           : firmware_version.h
  * @brief          : Firmware version constants
  ******************************************************************************
  *
  * FW_GIT_HASH is injected at build time by CMake via -DFW_GIT_HASH="<hash>".
  * Falls back to "unknown" if not building through CMake.
  *
  ******************************************************************************
  */

#ifndef INC_FIRMWARE_VERSION_H_
#define INC_FIRMWARE_VERSION_H_

/* Exported defines ----------------------------------------------------------*/

#define FW_VER_MAJOR  1
#define FW_VER_MINOR  0
#define FW_VER_PATCH  0

#ifndef FW_GIT_HASH
#define FW_GIT_HASH  "unknown"
#endif

/* Two-step stringification so FW_VER_* expand before becoming a string. */
#define FW_STRINGIFY_(x)  #x
#define FW_STRINGIFY(x)   FW_STRINGIFY_(x)

/** @brief Human-readable version string stored in flash, e.g. "1.0.0+abc1234" */
#define FW_VERSION_STR  FW_STRINGIFY(FW_VER_MAJOR) "." \
                        FW_STRINGIFY(FW_VER_MINOR) "." \
                        FW_STRINGIFY(FW_VER_PATCH) "+" \
                        FW_GIT_HASH

#endif /* INC_FIRMWARE_VERSION_H_ */
