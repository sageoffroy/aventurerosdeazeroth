get_filename_component(
    AVENTUREROS_PROGRESSION_MODULE_DIR
    "${CMAKE_CURRENT_LIST_FILE}"
    DIRECTORY
)

# Lua-only module. The complete tree is staged next to ALE.
install(
    DIRECTORY
        "${AVENTUREROS_PROGRESSION_MODULE_DIR}/lua/"
    DESTINATION
        "bin/lua_scripts"
    FILES_MATCHING
        PATTERN "*.lua"
)
