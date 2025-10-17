
#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
struct PluginSlotState{ juce::String pluginID; juce::String format; juce::MemoryBlock state; bool bypassed=false; };
struct ChainState{ juce::Array<PluginSlotState> slots; float wetMix=1.0f; /* 0..1 */ };
struct SessionState{ ChainState bankA; ChainState bankB; juce::String activeBank="A"; };
struct SessionIO{
  static juce::var toVar(const SessionState& s);
  static bool fromVar(const juce::var& v, SessionState& out);
  static bool saveToFile(const juce::File& f, const SessionState& s);
  static bool loadFromFile(const juce::File& f, SessionState& s);
};
