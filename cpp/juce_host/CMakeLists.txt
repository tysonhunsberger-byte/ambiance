cmake_minimum_required(VERSION 3.20)

project(JucePluginHost VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT DEFINED JUCE_ROOT)
  if(DEFINED ENV{JUCE_ROOT})
    set(JUCE_ROOT $ENV{JUCE_ROOT})
  else()
    message(FATAL_ERROR "JUCE_ROOT not specified. Set the JUCE_ROOT cache variable or environment variable to the JUCE sources.")
  endif()
endif()

set(JUCE_SOURCE_DIR "${JUCE_ROOT}")

list(APPEND CMAKE_MODULE_PATH "${JUCE_SOURCE_DIR}/extras/Build/CMake")

include(FetchContent OPTIONAL)

if(NOT TARGET juce::juce_core)
  add_subdirectory("${JUCE_SOURCE_DIR}" "${CMAKE_BINARY_DIR}/JUCE" EXCLUDE_FROM_ALL)
endif()

juce_add_gui_app(JucePluginHost
  PRODUCT_NAME "Ambiance JUCE Plugin Host"
  VERSION ${PROJECT_VERSION}
  COMPANY_NAME "Ambiance"
  COPY_PLUGIN_AFTER_BUILD FALSE
)

target_sources(JucePluginHost PRIVATE src/Main.cpp)

target_compile_definitions(JucePluginHost
  PRIVATE
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_MODAL_LOOPS_PERMITTED=1
)

target_link_libraries(JucePluginHost
  PRIVATE
    juce::juce_gui_extra
    juce::juce_audio_utils
    juce::juce_audio_processors
)

