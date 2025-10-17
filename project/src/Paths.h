
#pragma once
#include <juce_core/juce_core.h>
struct DefaultPluginPaths {
    static juce::StringArray vst3(){
        juce::StringArray p;
       #if JUCE_WINDOWS
        p.add("C:\\\\Program Files\\\\Common Files\\\\VST3");
        p.add("C:\\\\Program Files (x86)\\\\Common Files\\\\VST3");
       #elif JUCE_MAC
        p.add("/Library/Audio/Plug-Ins/VST3");
        p.add(juce::File::getSpecialLocation(juce::File::userHomeDirectory)
              .getChildFile("Library/Audio/Plug-Ins/VST3").getFullPathName());
       #else
        p.add("~/.vst3"); p.add("/usr/lib/vst3"); p.add("/usr/local/lib/vst3");
       #endif
        return p;
    }
    static juce::StringArray vst2(){
        juce::StringArray p;
       #if JUCE_WINDOWS
        p.add("C:\\\\Program Files\\\\Steinberg\\\\VstPlugins");
        p.add("C:\\\\Program Files (x86)\\\\Steinberg\\\\VstPlugins");
       #elif JUCE_MAC
        p.add("/Library/Audio/Plug-Ins/VST");
       #else
        p.add("~/.vst"); p.add("/usr/lib/vst"); p.add("/usr/local/lib/vst");
       #endif
        return p;
    }
    static juce::StringArray au(){
        juce::StringArray p;
       #if JUCE_MAC
        p.add("/Library/Audio/Plug-Ins/Components");
       #endif
        return p;
    }
};
