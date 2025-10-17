
cmake_minimum_required(VERSION 3.20)
project(AmbianceHost VERSION 0.3 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
FetchContent_Declare(
  juce
  GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
  GIT_TAG 7.0.12
  GIT_SHALLOW TRUE
  GIT_CONFIG core.longpaths=true
)
FetchContent_MakeAvailable(juce)

add_compile_definitions(JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_PLUGINHOST_VST3=1)
if(APPLE)
  add_compile_definitions(JUCE_PLUGINHOST_AU=1)
endif()

option(JUCE_ENABLE_VST2 "Enable VST2 hosting (requires VST2 SDK + license)" OFF)
if(JUCE_ENABLE_VST2)
  if(NOT VST2_SDK_DIR)
    message(FATAL_ERROR "VST2 hosting requested but VST2_SDK_DIR not set.")
  endif()
  add_compile_definitions(JUCE_PLUGINHOST_VST=1)
  add_library(vst2_sdk INTERFACE)
  target_include_directories(vst2_sdk INTERFACE ${VST2_SDK_DIR})
endif()

juce_add_gui_app(AmbianceHost COMPANY_NAME "Ambiance" PRODUCT_NAME "AmbianceHost")

target_sources(AmbianceHost PRIVATE
  src/Main.cpp
  src/MainComponent.h
  src/MainComponent.cpp
  src/Session.h
  src/Session.cpp
  src/Paths.h
  src/GainProcessor.h
  src/GainProcessor.cpp
)

target_compile_definitions(AmbianceHost PRIVATE JUCE_DISPLAY_SPLASH_SCREEN=0 JUCE_REPORT_APP_USAGE=0)
target_link_libraries(AmbianceHost PRIVATE
  juce::juce_gui_extra
  juce::juce_audio_utils
  juce::juce_audio_devices
  juce::juce_audio_processors
  juce::juce_dsp
)
if(JUCE_ENABLE_VST2)
  target_link_libraries(AmbianceHost PRIVATE vst2_sdk)
endif()
