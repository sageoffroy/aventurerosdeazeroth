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

# draft_core.inc is intentionally not a .lua file: ALE must not auto-execute it.
# The small draft.lua wrapper loads it explicitly after installing the talent
# integration hooks.
install(
    FILES
        "${SPELLDRAFT_MODULE_DIR}/lua/SpellDraft/draft_core.inc"
    DESTINATION
        "bin/lua_scripts/SpellDraft"
)
