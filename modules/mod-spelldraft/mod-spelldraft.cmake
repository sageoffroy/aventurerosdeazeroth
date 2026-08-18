get_filename_component(
    SPELLDRAFT_MODULE_DIR
    "${CMAKE_CURRENT_LIST_FILE}"
    DIRECTORY
)

install(
    FILES
        "${SPELLDRAFT_MODULE_DIR}/lua/spelldraft_bootstrap.lua"
    DESTINATION
        "bin/lua_scripts"
)
