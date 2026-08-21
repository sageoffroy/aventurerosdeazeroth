# Aventureros de Azeroth - repository-owned overlays for external modules.
#
# mod-dungeon-master is intentionally kept as an upstream git submodule. Our
# project-specific fixes live in patches/mod-dungeon-master and are applied here
# before CMake configures that module. Since this directory sorts before
# mod-dungeon-master, its CMakeLists.txt runs first during AzerothCore module
# discovery.

get_filename_component(
    AVENTUREROS_ROOT
    "${CMAKE_CURRENT_SOURCE_DIR}/../.."
    ABSOLUTE
)

set(
    AVENTUREROS_PATCH_SCRIPT
    "${AVENTUREROS_ROOT}/tools/apply-module-patches.sh"
)

set(
    AVENTUREROS_DM_SOURCE
    "${AVENTUREROS_ROOT}/modules/mod-dungeon-master/src/DungeonMasterMgr.cpp"
)

if(EXISTS "${AVENTUREROS_PATCH_SCRIPT}" AND EXISTS "${AVENTUREROS_DM_SOURCE}")
    execute_process(
        COMMAND bash "${AVENTUREROS_PATCH_SCRIPT}"
        WORKING_DIRECTORY "${AVENTUREROS_ROOT}"
        RESULT_VARIABLE AVENTUREROS_PATCH_RESULT
        OUTPUT_VARIABLE AVENTUREROS_PATCH_OUTPUT
        ERROR_VARIABLE AVENTUREROS_PATCH_ERROR
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_STRIP_TRAILING_WHITESPACE
    )

    if(AVENTUREROS_PATCH_OUTPUT)
        message(STATUS "Aventureros module patches: ${AVENTUREROS_PATCH_OUTPUT}")
    endif()

    if(NOT AVENTUREROS_PATCH_RESULT EQUAL 0)
        message(FATAL_ERROR
            "Failed to apply Aventureros module patches:\n${AVENTUREROS_PATCH_ERROR}"
        )
    endif()
endif()
