
#pragma once
#include <juce_audio_processors/juce_audio_processors.h>

class GainProcessor : public juce::AudioProcessor
{
public:
    GainProcessor() {}
    const juce::String getName() const override { return "GainProcessor"; }
    void prepareToPlay (double, int) override {}
    void releaseResources() override {}
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override
    {
        return layouts.getMainInputChannelSet() == layouts.getMainOutputChannelSet();
    }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }
    bool hasEditor() const override { return false; }
    juce::AudioProcessorEditor* createEditor() override { return nullptr; }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void setGain (float g) { gain.store (g); }
    float getGain() const { return gain.load(); }

    void processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&) override
    {
        buffer.applyGain (gain.load());
    }
    void getStateInformation (juce::MemoryBlock& destData) override
    {
        auto g = gain.load(); destData.replaceWith(&g, sizeof(float));
    }
    void setStateInformation (const void* data, int sizeInBytes) override
    {
        if (sizeInBytes >= (int)sizeof(float)) { float g; memcpy(&g, data, sizeof(float)); setGain(g); }
    }
private:
    std::atomic<float> gain { 1.0f };
};
