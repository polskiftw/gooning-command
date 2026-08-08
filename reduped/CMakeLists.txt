cmake_minimum_required(VERSION 3.24)
project(Reduped VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
if(MSVC)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

find_package(SQLite3 REQUIRED)

add_library(reduped_core STATIC
    src/config.cpp
    src/database.cpp
    src/fingerprint.cpp
    src/matcher.cpp
    src/generation.cpp
    src/deletion.cpp
    src/pipeline.cpp
)
target_include_directories(reduped_core PUBLIC include)
target_link_libraries(reduped_core PUBLIC SQLite::SQLite3)
target_compile_definitions(reduped_core PUBLIC REDUPED_VERSION="${PROJECT_VERSION}")
if(MSVC)
    target_compile_options(reduped_core PRIVATE /W4 /permissive- /EHsc /utf-8)
else()
    target_compile_options(reduped_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(WIN32)
    find_package(nlohmann_json CONFIG REQUIRED)
    add_executable(reduped WIN32
        src/main_win32.cpp
        src/app_win32.cpp
        src/r2_winhttp.cpp
        src/evidence_windows.cpp
        src/preview_windows.cpp
        resources/reduped.rc
    )
    target_include_directories(reduped PRIVATE include)
    target_link_libraries(reduped PRIVATE
        reduped_core
        nlohmann_json::nlohmann_json
        bcrypt
        comctl32
        crypt32
        d2d1
        dwrite
        mf
        mfplat
        mfreadwrite
        mfuuid
        ole32
        shell32
        shlwapi
        windowscodecs
        winhttp
    )
    target_compile_definitions(reduped PRIVATE UNICODE _UNICODE NOMINMAX WIN32_LEAN_AND_MEAN)
    set_target_properties(reduped PROPERTIES OUTPUT_NAME "Reduped")
    install(TARGETS reduped RUNTIME DESTINATION .)
    install(FILES config.example.txt README.md DGD.md DESTINATION .)
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(reduped_tests tests/test_main.cpp tests/fake_store.cpp)
    target_include_directories(reduped_tests PRIVATE include tests)
    target_link_libraries(reduped_tests PRIVATE reduped_core)
    add_test(NAME reduped_behavior COMMAND reduped_tests)

    add_executable(reduped_benchmark tests/benchmark_matcher.cpp)
    target_include_directories(reduped_benchmark PRIVATE include)
    target_link_libraries(reduped_benchmark PRIVATE reduped_core)
endif()
