get_filename_component(
    SPELLDRAFT_MODULE_DIR
    "${CMAKE_CURRENT_LIST_FILE}"
    DIRECTORY
)

# Keep every SpellDraft Lua file versioned inside the module and stage the
# complete tree next to ALE at install time. New runtime scripts therefore do
# not require adding another CMake install rule.
install(
    DIRECTORY
        "${SPELLDRAFT_MODULE_DIR}/lua/"
    DESTINATION
        "bin/lua_scripts"
    FILES_MATCHING
        PATTERN "*.lua"
)
