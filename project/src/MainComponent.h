
#pragma once
#include <juce_audio_utils/juce_audio_utils.h>
#include <vector>
#include "Session.h"
#include "Paths.h"
#include "GainProcessor.h"

class MainComponent : public juce::Component,
                      private juce::Button::Listener,
                      private juce::Slider::Listener,
                      private juce::ComboBox::Listener,
                      private juce::ChangeListener {
public:
  MainComponent();
  ~MainComponent() override;
  void paint(juce::Graphics&) override;
  void resized() override;
private:
  struct ThemePalette{
    juce::Colour background;
    juce::Colour toolbar;
    juce::Colour toolbarHighlight;
    juce::Colour panel;
    juce::Colour card;
    juce::Colour cardBorder;
    juce::Colour accent;
    juce::Colour text;
    juce::Colour muted;
  };

  class ToolbarComponent;
  class ChainPanelComponent;
  class WorkspaceComponent;
  class SlotComponent;

  enum class Theme { flat = 1, win98, winxp };

  ThemePalette palette{};
  Theme currentTheme = Theme::flat;

  ToolbarComponent toolbar;
  juce::Label titleLabel;
  juce::TextButton startAudioButton{"🎵 Start Audio"};
  juce::TextButton addStreamTopButton{"➕ Add Stream"};
  juce::TextButton editToggleButton{"✏️ Edit: OFF"};
  juce::TextButton styleModeButton{"🎨 Style Mode: OFF"};
  juce::ComboBox themePicker;
  juce::TextButton saveButton{"💾 Save"};
  juce::TextButton loadButton{"📂 Load"};

  juce::Viewport workspaceViewport;
  WorkspaceComponent workspace;
  ChainPanelComponent chainPanel;
  juce::Label chainTitleLabel;
  juce::TextButton scanButton{"Scan"};
  juce::TextButton addStreamButton{"Add Stream"};
  juce::TextButton bankButton{"Switch Bank (A/B)"};
  juce::Label mixLabel;
  juce::Slider mixSlider;
  juce::Label mixValueLabel;
  juce::Label latencyLabel;
  juce::Component slotsContainer;
  juce::Label emptyLabel;

  std::vector<std::unique_ptr<SlotComponent>> slotComponents;
  int selectedSlot = -1;
  bool editMode = false;
  bool styleMode = false;

  // Audio + hosting
  juce::AudioDeviceManager deviceManager;
  juce::AudioPluginFormatManager formatManager;
  juce::KnownPluginList knownPlugins;
  std::unique_ptr<juce::AudioProcessorGraph> graph;
  std::unique_ptr<juce::AudioProcessorPlayer> player;

  // Nodes
  juce::AudioProcessorGraph::NodeID inputNodeID{1}, outputNodeID{2}, midiInputNodeID{3};
  GainProcessor* dryGainProc=nullptr; // owned by graph nodes
  GainProcessor* wetGainProc=nullptr;

  // Banks
  SessionState session; ChainState* activeChain=nullptr;

  // Async chooser must persist
  std::unique_ptr<juce::FileChooser> chooser;

  // Helpers
  void buttonClicked(juce::Button*) override;
  void sliderValueChanged(juce::Slider*) override;
  void comboBoxChanged(juce::ComboBox*) override;
  void changeListenerCallback(juce::ChangeBroadcaster*) override;
  void buildAudioGraph();
  void rebuildGraphFromSession();
  void refreshChainList();
  void layoutWorkspace();
  void layoutSlots();
  int computeSlotsHeight() const;
  bool addPluginFromFile(const juce::File& f);
  void openSelectedEditor();
  void removeSelected();
  void moveSelected(int delta);
  void toggleBypass();
  void doScan();
  void saveSession();
  void loadSession();
  void updateMixGains();
  void updateLatencyLabel();
  void addPluginViaChooser();
  void selectSlot(int index);
  void openSlotEditor(int index);
  void removeSlot(int index);
  void moveSlot(int index, int delta);
  void setSlotBypass(int index, bool shouldBypass);
  void updateMixDisplay();
  void applyTheme(Theme theme);
  void updateThemeButtonStates();
  void startAudioEngine();
  juce::String slotDisplayName(const PluginSlotState& slot) const;
  static bool findDescriptionForFile(juce::AudioPluginFormatManager& fm, const juce::String& fileOrIdentifier, juce::PluginDescription& out);
  JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(MainComponent)
};
