
#include "MainComponent.h"
#include <algorithm>
#include <cmath>

bool MainComponent::findDescriptionForFile(juce::AudioPluginFormatManager& fm, const juce::String& fileOrIdentifier, juce::PluginDescription& out)
{
    juce::OwnedArray<juce::PluginDescription> types;
    for (int i = 0; i < fm.getNumFormats(); ++i)
        fm.getFormat(i)->findAllTypesForFile(types, fileOrIdentifier);
    if (types.isEmpty())
        return false;
    out = *types[0];
    return true;
}

class PluginEditorWindow : public juce::DialogWindow
{
public:
    PluginEditorWindow(const juce::PluginDescription& desc,
                       std::unique_ptr<juce::AudioPluginInstance> inst,
                       std::function<void(juce::MemoryBlock&)> onSave)
        : juce::DialogWindow(desc.name, juce::Colours::black, true),
          instance(std::move(inst)),
          saveCb(std::move(onSave))
    {
        setUsingNativeTitleBar(true);
        setResizable(true, true);
        if (auto* ed = instance->createEditorIfNeeded())
        {
            setContentOwned(ed, true);
            setResizable(true, true);
            centreWithSize(std::max(480, ed->getWidth()), std::max(320, ed->getHeight()));
            setVisible(true);
        }
        else
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon, "No editor", "This plug-in has no GUI.");
            delete this;
        }
    }

    void closeButtonPressed() override
    {
        juce::MemoryBlock mb;
        if (instance)
            instance->getStateInformation(mb);
        if (saveCb)
            saveCb(mb);
        delete this;
    }

private:
    std::unique_ptr<juce::AudioPluginInstance> instance;
    std::function<void(juce::MemoryBlock&)> saveCb;
};

class MainComponent::ToolbarComponent : public juce::Component
{
public:
    explicit ToolbarComponent(MainComponent& owner) : parent(owner) {}

    void paint(juce::Graphics& g) override
    {
        auto area = getLocalBounds().toFloat();
        if (parent.currentTheme == Theme::winxp)
        {
            juce::ColourGradient gradient(parent.palette.toolbar, 0.0f, 0.0f,
                                          parent.palette.toolbarHighlight, 0.0f, area.getHeight(), false);
            g.setGradientFill(gradient);
            g.fillRect(area);
        }
        else
        {
            g.setColour(parent.palette.toolbar);
            g.fillRect(area);
            if (parent.currentTheme == Theme::win98)
            {
                g.setColour(parent.palette.cardBorder);
                g.drawRect(getLocalBounds(), 2);
            }
        }
    }

private:
    MainComponent& parent;
};

class MainComponent::WorkspaceComponent : public juce::Component
{
public:
    explicit WorkspaceComponent(MainComponent& owner) : parent(owner) {}

    void paint(juce::Graphics& g) override
    {
        if (parent.currentTheme == Theme::winxp)
        {
            juce::ColourGradient gradient(parent.palette.background, 0.0f, 0.0f,
                                          parent.palette.toolbarHighlight, 0.0f, (float)getHeight(), false);
            g.setGradientFill(gradient);
            g.fillAll();
        }
        else
        {
            g.setColour(parent.palette.background);
            g.fillAll();
        }
    }

private:
    MainComponent& parent;
};

class MainComponent::ChainPanelComponent : public juce::Component
{
public:
    explicit ChainPanelComponent(MainComponent& owner) : parent(owner) {}

    void paint(juce::Graphics& g) override
    {
        auto bounds = getLocalBounds();

        if (parent.currentTheme == Theme::win98)
        {
            g.setColour(parent.palette.panel);
            g.fillRect(bounds.reduced(2));
            g.setColour(juce::Colours::white);
            g.drawLine((float)bounds.getX(), (float)bounds.getY(), (float)bounds.getRight(), (float)bounds.getY(), 2.0f);
            g.drawLine((float)bounds.getX(), (float)bounds.getY(), (float)bounds.getX(), (float)bounds.getBottom(), 2.0f);
            g.setColour(parent.palette.cardBorder.darker(0.4f));
            g.drawLine((float)bounds.getRight(), (float)bounds.getY(), (float)bounds.getRight(), (float)bounds.getBottom(), 2.0f);
            g.drawLine((float)bounds.getX(), (float)bounds.getBottom(), (float)bounds.getRight(), (float)bounds.getBottom(), 2.0f);
        }
        else
        {
            juce::DropShadow shadow(parent.palette.cardBorder.withAlpha(0.35f),
                                    parent.currentTheme == Theme::flat ? 12 : 6,
                                    juce::Point<int>());
            shadow.drawForRectangle(g, bounds);
            auto inner = bounds.toFloat().reduced(2.0f);
            auto radius = parent.currentTheme == Theme::flat ? 12.0f : 8.0f;
            g.setColour(parent.palette.panel);
            g.fillRoundedRectangle(inner, radius);
            g.setColour(parent.palette.cardBorder);
            g.drawRoundedRectangle(inner, radius, 1.5f);
        }
    }

private:
    MainComponent& parent;
};

class MainComponent::SlotComponent : public juce::Component,
                                     private juce::Button::Listener
{
public:
    SlotComponent(MainComponent& owner, int slotIndex)
        : parent(owner), index(slotIndex)
    {
        addAndMakeVisible(nameLabel);
        nameLabel.setJustificationType(juce::Justification::centredLeft);
        nameLabel.setFont(juce::Font(16.0f, juce::Font::bold));
        nameLabel.setMinimumHorizontalScale(0.6f);
        nameLabel.setEllipsiseMode(juce::Label::EllipsiseMode::end);

        addAndMakeVisible(formatLabel);
        formatLabel.setJustificationType(juce::Justification::centredLeft);
        formatLabel.setFont(juce::Font(13.0f));

        addAndMakeVisible(pathLabel);
        pathLabel.setJustificationType(juce::Justification::centredLeft);
        pathLabel.setFont(juce::Font(12.0f));
        pathLabel.setMinimumHorizontalScale(0.6f);
        pathLabel.setEllipsiseMode(juce::Label::EllipsiseMode::end);

        bypassToggle.setButtonText("Bypass");
        addAndMakeVisible(bypassToggle);
        bypassToggle.addListener(this);

        addAndMakeVisible(openButton);
        openButton.addListener(this);

        addAndMakeVisible(removeButton);
        removeButton.addListener(this);

        addAndMakeVisible(upButton);
        upButton.addListener(this);

        addAndMakeVisible(downButton);
        downButton.addListener(this);

        refreshTheme();
    }

    void update(const PluginSlotState& slot, bool isSelected)
    {
        displayName = parent.slotDisplayName(slot);
        updateNameLabel();
        formatLabel.setText(slot.format.isNotEmpty() ? slot.format : juce::String("Unknown"), juce::dontSendNotification);
        formatLabel.setTooltip(slot.format);
        pathLabel.setText(slot.pluginID, juce::dontSendNotification);
        pathLabel.setTooltip(slot.pluginID);
        bypassToggle.setToggleState(slot.bypassed, juce::dontSendNotification);
        selected = isSelected;
        refreshTheme();
        repaint();
    }

    void paint(juce::Graphics& g) override
    {
        auto bounds = getLocalBounds().toFloat().reduced(4.0f);
        auto radius = parent.currentTheme == Theme::flat ? 10.0f : 6.0f;
        auto bg = parent.palette.card;
        if (selected)
            bg = bg.interpolatedWith(parent.palette.accent, 0.18f);
        g.setColour(bg);
        g.fillRoundedRectangle(bounds, radius);

        auto border = selected ? parent.palette.accent : parent.palette.cardBorder;
        g.setColour(border);
        g.drawRoundedRectangle(bounds, radius, selected ? 2.4f : 1.2f);
    }

    void resized() override
    {
        auto area = getLocalBounds().reduced(18, 14);

        auto header = area.removeFromTop(28);
        auto bypassArea = header.removeFromRight(100);
        bypassToggle.setBounds(bypassArea);
        auto formatArea = header.removeFromRight(140);
        formatLabel.setBounds(formatArea);
        nameLabel.setBounds(header);

        area.removeFromTop(6);
        auto pathArea = area.removeFromTop(20);
        pathLabel.setBounds(pathArea);

        area.removeFromTop(8);
        auto buttons = area.removeFromTop(32);
        openButton.setBounds(buttons.removeFromLeft(120));
        buttons.removeFromLeft(8);
        removeButton.setBounds(buttons.removeFromLeft(100));
        buttons.removeFromLeft(8);
        upButton.setBounds(buttons.removeFromLeft(40));
        buttons.removeFromLeft(6);
        downButton.setBounds(buttons.removeFromLeft(40));
    }

    void mouseUp(const juce::MouseEvent& e) override
    {
        if (e.mouseWasClicked())
            parent.selectSlot(index);
    }

    void buttonClicked(juce::Button* b) override
    {
        parent.selectSlot(index);
        if (b == &bypassToggle)
        {
            parent.setSlotBypass(index, bypassToggle.getToggleState());
        }
        else if (b == &openButton)
        {
            parent.openSlotEditor(index);
        }
        else if (b == &removeButton)
        {
            parent.removeSlot(index);
        }
        else if (b == &upButton)
        {
            parent.moveSlot(index, -1);
        }
        else if (b == &downButton)
        {
            parent.moveSlot(index, +1);
        }
    }

    void setIndex(int newIndex)
    {
        index = newIndex;
        updateNameLabel();
    }

    void setSelected(bool shouldSelect)
    {
        if (selected != shouldSelect)
        {
            selected = shouldSelect;
            repaint();
        }
    }

    void refreshTheme()
    {
        nameLabel.setColour(juce::Label::textColourId, parent.palette.text);
        formatLabel.setColour(juce::Label::textColourId, parent.palette.muted);
        pathLabel.setColour(juce::Label::textColourId, parent.palette.muted.withMultipliedAlpha(0.9f));
        bypassToggle.setColour(juce::ToggleButton::textColourId, parent.palette.text);
        bypassToggle.setColour(juce::ToggleButton::tickColourId, parent.palette.accent);

        auto setColours = [this](juce::Button& button)
        {
            button.setColour(juce::TextButton::buttonColourId, parent.palette.card);
            button.setColour(juce::TextButton::textColourOff, parent.palette.text);
            button.setColour(juce::TextButton::textColourOn, parent.palette.text);
            button.setColour(juce::TextButton::buttonOnColourId, parent.palette.accent.withAlpha(0.65f));
        };

        setColours(openButton);
        setColours(removeButton);
        setColours(upButton);
        setColours(downButton);
    }

    static int defaultHeight() { return 132; }
    int getPreferredHeight() const { return defaultHeight(); }

private:
    void updateNameLabel()
    {
        nameLabel.setText(juce::String(index + 1) + ". " + displayName, juce::dontSendNotification);
    }

    MainComponent& parent;
    int index = 0;
    bool selected = false;
    juce::String displayName;
    juce::Label nameLabel;
    juce::Label formatLabel;
    juce::Label pathLabel;
    juce::ToggleButton bypassToggle;
    juce::TextButton openButton{"Open Editor"};
    juce::TextButton removeButton{"Remove"};
    juce::TextButton upButton{"▲"};
    juce::TextButton downButton{"▼"};
};

MainComponent::MainComponent()
    : toolbar(*this),
      workspace(*this),
      chainPanel(*this)
{
    setSize(1100, 720);

    deviceManager.initialise(0, 2, nullptr, true, {}, nullptr);
    formatManager.addDefaultFormats();
    graph = std::make_unique<juce::AudioProcessorGraph>();
    player = std::make_unique<juce::AudioProcessorPlayer>();
    player->setProcessor(graph.get());
    deviceManager.addAudioCallback(player.get());
    session.activeBank = "A";
    activeChain = &session.bankA;

    addAndMakeVisible(toolbar);
    toolbar.addAndMakeVisible(titleLabel);
    titleLabel.setText("Noisetown Ultimate", juce::dontSendNotification);
    titleLabel.setJustificationType(juce::Justification::centredLeft);
    titleLabel.setFont(juce::Font(21.0f, juce::Font::bold));

    auto addToolbarButton = [this](juce::TextButton& button)
    {
        toolbar.addAndMakeVisible(button);
        button.addListener(this);
    };

    addToolbarButton(startAudioButton);
    addToolbarButton(addStreamTopButton);
    addToolbarButton(editToggleButton);
    addToolbarButton(styleModeButton);
    editToggleButton.setClickingTogglesState(true);
    styleModeButton.setClickingTogglesState(true);

    toolbar.addAndMakeVisible(themePicker);
    themePicker.addListener(this);
    themePicker.addItem("Theme: Flat (Default)", (int)Theme::flat);
    themePicker.addItem("Theme: Windows 98", (int)Theme::win98);
    themePicker.addItem("Theme: Windows XP", (int)Theme::winxp);

    addToolbarButton(saveButton);
    addToolbarButton(loadButton);

    addAndMakeVisible(workspaceViewport);
    workspaceViewport.setViewedComponent(&workspace, false);
    workspaceViewport.setScrollBarsShown(true, false);

    workspace.addAndMakeVisible(chainPanel);
    chainPanel.addAndMakeVisible(chainTitleLabel);
    chainTitleLabel.setJustificationType(juce::Justification::centredLeft);
    chainTitleLabel.setFont(juce::Font(18.0f, juce::Font::bold));

    auto addChainButton = [this](juce::TextButton& button)
    {
        chainPanel.addAndMakeVisible(button);
        button.addListener(this);
    };

    addChainButton(scanButton);
    addChainButton(addStreamButton);
    addChainButton(bankButton);

    chainPanel.addAndMakeVisible(mixLabel);
    mixLabel.setText("Wet Mix", juce::dontSendNotification);
    chainPanel.addAndMakeVisible(mixSlider);
    mixSlider.setSliderStyle(juce::Slider::LinearHorizontal);
    mixSlider.setTextBoxStyle(juce::Slider::NoTextBox, false, 0, 0);
    mixSlider.setRange(0.0, 100.0, 1.0);
    mixSlider.setValue(100.0);
    mixSlider.addListener(this);

    chainPanel.addAndMakeVisible(mixValueLabel);
    mixValueLabel.setJustificationType(juce::Justification::centredLeft);

    chainPanel.addAndMakeVisible(latencyLabel);
    latencyLabel.setJustificationType(juce::Justification::centredRight);
    latencyLabel.setText("Latency: 0 samples", juce::dontSendNotification);

    chainPanel.addAndMakeVisible(slotsContainer);
    chainPanel.addAndMakeVisible(emptyLabel);
    emptyLabel.setJustificationType(juce::Justification::centred);
    emptyLabel.setText("No plug-ins loaded. Use \"Add Stream\" to insert one.", juce::dontSendNotification);

    themePicker.setSelectedId((int)currentTheme, juce::dontSendNotification);
    applyTheme(currentTheme);
    updateThemeButtonStates();
    updateMixDisplay();

    buildAudioGraph();
    refreshChainList();
}

MainComponent::~MainComponent()
{
    deviceManager.removeAudioCallback(player.get());
    if (player)
        player->setProcessor(nullptr);
    player.reset();
    graph.reset();
}

void MainComponent::paint(juce::Graphics& g)
{
    if (currentTheme == Theme::winxp)
    {
        juce::ColourGradient gradient(palette.background, 0.0f, 0.0f,
                                      palette.toolbarHighlight, 0.0f, (float)getHeight(), false);
        g.setGradientFill(gradient);
        g.fillAll();
    }
    else
    {
        g.setColour(palette.background);
        g.fillAll();
    }
}

void MainComponent::resized()
{
    auto bounds = getLocalBounds();
    auto toolbarBounds = bounds.removeFromTop(64);
    toolbar.setBounds(toolbarBounds);

    auto tb = toolbar.getLocalBounds().reduced(16, 10);
    auto row = tb;

    titleLabel.setBounds(row.removeFromLeft(220));
    row.removeFromLeft(12);
    startAudioButton.setBounds(row.removeFromLeft(140));
    row.removeFromLeft(8);
    addStreamTopButton.setBounds(row.removeFromLeft(160));
    row.removeFromLeft(8);
    editToggleButton.setBounds(row.removeFromLeft(140));
    row.removeFromLeft(8);
    styleModeButton.setBounds(row.removeFromLeft(180));
    row.removeFromLeft(12);
    themePicker.setBounds(row.removeFromLeft(220));
    row.removeFromLeft(8);
    saveButton.setBounds(row.removeFromLeft(110));
    row.removeFromLeft(8);
    loadButton.setBounds(row.removeFromLeft(110));

    bounds.removeFromTop(8);
    workspaceViewport.setBounds(bounds);

    layoutWorkspace();
}

void MainComponent::buttonClicked(juce::Button* b)
{
    if (b == &startAudioButton)
    {
        startAudioEngine();
    }
    else if (b == &addStreamTopButton || b == &addStreamButton)
    {
        addPluginViaChooser();
    }
    else if (b == &scanButton)
    {
        doScan();
    }
    else if (b == &bankButton)
    {
        session.activeBank = (session.activeBank == "A" ? "B" : "A");
        activeChain = (session.activeBank == "A" ? &session.bankA : &session.bankB);
        updateThemeButtonStates();
        rebuildGraphFromSession();
    }
    else if (b == &saveButton)
    {
        saveSession();
    }
    else if (b == &loadButton)
    {
        loadSession();
    }
    else if (b == &editToggleButton)
    {
        editMode = editToggleButton.getToggleState();
        updateThemeButtonStates();
    }
    else if (b == &styleModeButton)
    {
        styleMode = styleModeButton.getToggleState();
        updateThemeButtonStates();
    }
}

void MainComponent::sliderValueChanged(juce::Slider* s)
{
    if (s == &mixSlider)
    {
        activeChain->wetMix = (float)(mixSlider.getValue() / 100.0);
        updateMixGains();
        updateMixDisplay();
    }
}

void MainComponent::comboBoxChanged(juce::ComboBox* box)
{
    if (box == &themePicker)
    {
        auto id = themePicker.getSelectedId();
        if (id != 0)
        {
            applyTheme(static_cast<Theme>(id));
            refreshChainList();
        }
    }
}

void MainComponent::changeListenerCallback(juce::ChangeBroadcaster*){}

void MainComponent::buildAudioGraph()
{
    graph->clear();

    auto in = graph->addNode(std::make_unique<juce::AudioProcessorGraph::AudioGraphIOProcessor>(
        juce::AudioProcessorGraph::AudioGraphIOProcessor::audioInputNode));
    auto out = graph->addNode(std::make_unique<juce::AudioProcessorGraph::AudioGraphIOProcessor>(
        juce::AudioProcessorGraph::AudioGraphIOProcessor::audioOutputNode));
    auto midiIn = graph->addNode(std::make_unique<juce::AudioProcessorGraph::AudioGraphIOProcessor>(
        juce::AudioProcessorGraph::AudioGraphIOProcessor::midiInputNode));
    inputNodeID = in->nodeID;
    outputNodeID = out->nodeID;
    midiInputNodeID = midiIn->nodeID;

    rebuildGraphFromSession();
}

void MainComponent::rebuildGraphFromSession()
{
    juce::Array<juce::AudioProcessorGraph::Node::Ptr> toRemove;
    for (auto node : graph->getNodes())
        if (node->nodeID != inputNodeID && node->nodeID != outputNodeID && node->nodeID != midiInputNodeID)
            toRemove.add(node);
    for (auto node : toRemove)
        graph->removeNode(node->nodeID);

    dryGainProc = nullptr;
    wetGainProc = nullptr;

    auto last = inputNodeID;
    int totalLatency = 0;

    for (int idx = 0; idx < activeChain->slots.size(); ++idx)
    {
        auto& slot = activeChain->slots.getReference(idx);
        if (slot.bypassed)
            continue;

        juce::PluginDescription desc;
        if (!findDescriptionForFile(formatManager, slot.pluginID, desc))
            continue;

        juce::String err;
        auto inst = std::unique_ptr<juce::AudioPluginInstance>(formatManager.createPluginInstance(desc, 44100.0, 512, err));
        if (!inst)
            continue;

        if (slot.state.getSize() > 0)
            inst->setStateInformation(slot.state.getData(), (int)slot.state.getSize());

        auto node = graph->addNode(std::move(inst));

        graph->addConnection({ { last, 0 }, { node->nodeID, 0 } });
        graph->addConnection({ { last, 1 }, { node->nodeID, 1 } });
        graph->addConnection({ { midiInputNodeID, juce::AudioProcessorGraph::midiChannelIndex },
                               { node->nodeID, juce::AudioProcessorGraph::midiChannelIndex } });

        if (auto* p = dynamic_cast<juce::AudioProcessor*>(node->getProcessor()))
            totalLatency += p->getLatencySamples();

        last = node->nodeID;
    }

    auto wetNode = graph->addNode(std::unique_ptr<juce::AudioProcessor>(new GainProcessor()));
    wetGainProc = dynamic_cast<GainProcessor*>(wetNode->getProcessor());
    if (wetGainProc)
        wetGainProc->setGain(activeChain->wetMix);

    graph->addConnection({ { last, 0 }, { wetNode->nodeID, 0 } });
    graph->addConnection({ { last, 1 }, { wetNode->nodeID, 1 } });
    graph->addConnection({ { wetNode->nodeID, 0 }, { outputNodeID, 0 } });
    graph->addConnection({ { wetNode->nodeID, 1 }, { outputNodeID, 1 } });

    auto dryNode = graph->addNode(std::unique_ptr<juce::AudioProcessor>(new GainProcessor()));
    dryGainProc = dynamic_cast<GainProcessor*>(dryNode->getProcessor());
    if (dryGainProc)
        dryGainProc->setGain(1.0f - activeChain->wetMix);

    graph->addConnection({ { inputNodeID, 0 }, { dryNode->nodeID, 0 } });
    graph->addConnection({ { inputNodeID, 1 }, { dryNode->nodeID, 1 } });
    graph->addConnection({ { dryNode->nodeID, 0 }, { outputNodeID, 0 } });
    graph->addConnection({ { dryNode->nodeID, 1 }, { outputNodeID, 1 } });

    refreshChainList();
    updateMixGains();
    latencyLabel.setText("Latency: " + juce::String(totalLatency) + " samples", juce::dontSendNotification);
}

void MainComponent::refreshChainList()
{
    updateThemeButtonStates();

    while (slotsContainer.getNumChildComponents() > 0)
        slotsContainer.removeChildComponent(0, false);
    slotComponents.clear();

    for (int i = 0; i < activeChain->slots.size(); ++i)
    {
        auto comp = std::make_unique<SlotComponent>(*this, i);
        comp->update(activeChain->slots.getReference(i), i == selectedSlot);
        slotsContainer.addAndMakeVisible(comp.get());
        slotComponents.push_back(std::move(comp));
    }

    auto hasSlots = activeChain->slots.size() > 0;
    emptyLabel.setVisible(!hasSlots);
    slotsContainer.setVisible(hasSlots);

    updateMixDisplay();
    layoutWorkspace();
    selectSlot(selectedSlot);
}

void MainComponent::layoutWorkspace()
{
    int viewWidth = workspaceViewport.getWidth();
    if (viewWidth <= 0)
        viewWidth = getWidth();
    int panelWidth = juce::jmax(720, viewWidth - 40);

    int slotsHeight = computeSlotsHeight();
    int panelHeight = 16 + 32 + 12 + 40 + 8 + slotsHeight + 16;

    chainPanel.setBounds(20, 20, panelWidth, panelHeight);

    auto area = chainPanel.getLocalBounds().reduced(16);
    auto header = area.removeFromTop(32);
    chainTitleLabel.setBounds(header.removeFromLeft(juce::jmax(220, header.getWidth() - 280)));
    addStreamButton.setBounds(header.removeFromLeft(140));
    header.removeFromLeft(8);
    scanButton.setBounds(header.removeFromLeft(100));
    header.removeFromLeft(8);
    bankButton.setBounds(header.removeFromRight(160));

    area.removeFromTop(12);
    auto mixRow = area.removeFromTop(40);
    mixLabel.setBounds(mixRow.removeFromLeft(100));
    mixSlider.setBounds(mixRow.removeFromLeft(juce::jmin(360, mixRow.getWidth() - 160)));
    mixValueLabel.setBounds(mixRow.removeFromLeft(60));
    latencyLabel.setBounds(mixRow);

    area.removeFromTop(8);
    juce::Rectangle<int> slotsArea(area.getX(), area.getY(), area.getWidth(), slotsHeight);
    slotsContainer.setBounds(slotsArea);
    emptyLabel.setBounds(slotsArea);

    layoutSlots();

    workspace.setSize(panelWidth + 40, chainPanel.getBottom() + 20);
}

void MainComponent::layoutSlots()
{
    const int gap = 12;
    int y = 0;
    int width = slotsContainer.getWidth();
    for (size_t i = 0; i < slotComponents.size(); ++i)
    {
        auto& comp = slotComponents[i];
        comp->setIndex((int)i);
        comp->setBounds(0, y, width, SlotComponent::defaultHeight());
        comp->setSelected((int)i == selectedSlot);
        y += SlotComponent::defaultHeight() + gap;
    }
}

int MainComponent::computeSlotsHeight() const
{
    if (!activeChain || activeChain->slots.isEmpty())
        return SlotComponent::defaultHeight();
    const int gap = 12;
    return activeChain->slots.size() * SlotComponent::defaultHeight() + (activeChain->slots.size() - 1) * gap;
}

bool MainComponent::addPluginFromFile(const juce::File& f)
{
    juce::PluginDescription desc;
    if (!findDescriptionForFile(formatManager, f.getFullPathName(), desc))
    {
        juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::WarningIcon, "No plugin found", f.getFullPathName());
        return false;
    }

    juce::String err;
    auto inst = std::unique_ptr<juce::AudioPluginInstance>(formatManager.createPluginInstance(desc, 44100.0, 512, err));
    if (!inst)
    {
        juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::WarningIcon, "Load failed", err);
        return false;
    }

    PluginSlotState slot;
    slot.pluginID = desc.fileOrIdentifier;
    slot.format = desc.pluginFormatName;
    inst->prepareToPlay(44100.0, 512);
    inst->releaseResources();
    inst->getStateInformation(slot.state);
    activeChain->slots.add(std::move(slot));
    selectedSlot = activeChain->slots.size() - 1;
    rebuildGraphFromSession();
    selectSlot(selectedSlot);
    return true;
}

void MainComponent::openSelectedEditor()
{
    int row = selectedSlot;
    if (row < 0 || row >= activeChain->slots.size())
        return;
    auto slot = activeChain->slots[row];
    juce::PluginDescription desc;
    if (!findDescriptionForFile(formatManager, slot.pluginID, desc))
        return;
    juce::String err;
    auto inst = std::unique_ptr<juce::AudioPluginInstance>(formatManager.createPluginInstance(desc, 44100.0, 512, err));
    if (!inst)
        return;
    if (slot.state.getSize() > 0)
        inst->setStateInformation(slot.state.getData(), (int)slot.state.getSize());
    new PluginEditorWindow(desc, std::move(inst), [this, row](juce::MemoryBlock& mb)
    {
        auto& s = activeChain->slots.getReference(row);
        s.state = mb;
        rebuildGraphFromSession();
    });
}

void MainComponent::removeSelected()
{
    removeSlot(selectedSlot);
}

void MainComponent::moveSelected(int delta)
{
    moveSlot(selectedSlot, delta);
}

void MainComponent::toggleBypass()
{
    if (selectedSlot < 0 || selectedSlot >= activeChain->slots.size())
        return;
    auto& s = activeChain->slots.getReference(selectedSlot);
    setSlotBypass(selectedSlot, !s.bypassed);
}

void MainComponent::doScan()
{
    juce::FileSearchPath sp;
    for (auto& p : DefaultPluginPaths::vst3())
        sp.add(juce::File(p));
   #if JUCE_PLUGINHOST_VST
    for (auto& p : DefaultPluginPaths::vst2())
        sp.add(juce::File(p));
   #endif
   #if JUCE_MAC && JUCE_PLUGINHOST_AU
    for (auto& p : DefaultPluginPaths::au())
        sp.add(juce::File(p));
   #endif
    juce::AudioPluginFormat* format = nullptr;
    for (int i = 0; i < formatManager.getNumFormats(); ++i)
        if (formatManager.getFormat(i)->getName().containsIgnoreCase("VST3"))
        {
            format = formatManager.getFormat(i);
            break;
        }
    if (!format && formatManager.getNumFormats() > 0)
        format = formatManager.getFormat(0);
    if (!format)
    {
        juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::WarningIcon, "No formats", "No plugin formats available.");
        return;
    }
    juce::PluginDirectoryScanner scanner(knownPlugins, *format, sp, true, {}, false);
    juce::String nm;
    while (scanner.scanNextFile(true, nm)) {}
    juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon, "Scan finished", juce::String(knownPlugins.getNumTypes()) + " plugins known.");
}

void MainComponent::saveSession()
{
    chooser = std::make_unique<juce::FileChooser>("Save Ambiance session", juce::File(), "*.ambience.json");
    chooser->launchAsync(juce::FileBrowserComponent::saveMode | juce::FileBrowserComponent::canSelectFiles,
        [this](const juce::FileChooser& fc)
        {
            auto f = fc.getResult();
            if (f.getFileName().isNotEmpty())
                SessionIO::saveToFile(f, session);
            chooser.reset();
        });
}

void MainComponent::loadSession()
{
    chooser = std::make_unique<juce::FileChooser>("Load Ambiance session", juce::File(), "*.ambience.json");
    chooser->launchAsync(juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectFiles,
        [this](const juce::FileChooser& fc)
        {
            auto f = fc.getResult();
            if (f.existsAsFile())
            {
                SessionIO::loadFromFile(f, session);
                activeChain = (session.activeBank == "A" ? &session.bankA : &session.bankB);
                selectedSlot = -1;
                rebuildGraphFromSession();
            }
            chooser.reset();
        });
}

void MainComponent::updateMixGains()
{
    if (wetGainProc)
        wetGainProc->setGain(activeChain->wetMix);
    if (dryGainProc)
        dryGainProc->setGain(1.0f - activeChain->wetMix);
}

void MainComponent::updateLatencyLabel(){}

void MainComponent::addPluginViaChooser()
{
    chooser = std::make_unique<juce::FileChooser>("Choose a plug-in", juce::File(),
   #if JUCE_MAC
        "*.vst3;*.vst;*.component"
   #elif JUCE_WINDOWS
        "*.vst3;*.vst;*.dll"
   #else
        "*.vst3;*.so"
   #endif
    );
    chooser->launchAsync(juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectFiles,
        [this](const juce::FileChooser& fc)
        {
            auto f = fc.getResult();
            if (f.existsAsFile())
                addPluginFromFile(f);
            chooser.reset();
        });
}

void MainComponent::selectSlot(int index)
{
    if (!activeChain || activeChain->slots.isEmpty())
    {
        selectedSlot = -1;
    }
    else if (index < 0)
    {
        selectedSlot = -1;
    }
    else
    {
        selectedSlot = juce::jlimit(0, activeChain->slots.size() - 1, index);
    }

    for (size_t i = 0; i < slotComponents.size(); ++i)
        slotComponents[i]->setSelected((int)i == selectedSlot);
}

void MainComponent::openSlotEditor(int index)
{
    selectedSlot = index;
    openSelectedEditor();
}

void MainComponent::removeSlot(int index)
{
    if (!activeChain)
        return;
    auto safeThis = juce::Component::SafePointer<MainComponent>(this);
    juce::MessageManager::callAsync([safeThis, index]
    {
        if (auto* owner = safeThis.getComponent())
        {
            if (!owner->activeChain || index < 0 || index >= owner->activeChain->slots.size())
                return;
            owner->activeChain->slots.remove(index);
            owner->selectedSlot = juce::jlimit(-1, owner->activeChain->slots.size() - 1, index);
            owner->rebuildGraphFromSession();
            owner->selectSlot(owner->selectedSlot);
        }
    });
}

void MainComponent::moveSlot(int index, int delta)
{
    if (!activeChain)
        return;
    auto safeThis = juce::Component::SafePointer<MainComponent>(this);
    juce::MessageManager::callAsync([safeThis, index, delta]
    {
        if (auto* owner = safeThis.getComponent())
        {
            if (!owner->activeChain || index < 0 || index >= owner->activeChain->slots.size())
                return;
            int newIndex = juce::jlimit(0, owner->activeChain->slots.size() - 1, index + delta);
            if (newIndex == index)
                return;
            owner->activeChain->slots.move(index, newIndex);
            owner->selectedSlot = newIndex;
            owner->rebuildGraphFromSession();
            owner->selectSlot(owner->selectedSlot);
        }
    });
}

void MainComponent::setSlotBypass(int index, bool shouldBypass)
{
    if (!activeChain || index < 0 || index >= activeChain->slots.size())
        return;
    auto& slot = activeChain->slots.getReference(index);
    if (slot.bypassed == shouldBypass)
        return;
    slot.bypassed = shouldBypass;
    selectedSlot = index;
    auto safeThis = juce::Component::SafePointer<MainComponent>(this);
    juce::MessageManager::callAsync([safeThis, index]
    {
        if (auto* owner = safeThis.getComponent())
        {
            owner->rebuildGraphFromSession();
            owner->selectSlot(index);
        }
    });
}

void MainComponent::updateMixDisplay()
{
    mixSlider.setValue(activeChain->wetMix * 100.0, juce::dontSendNotification);
    mixValueLabel.setText(juce::String(std::round(activeChain->wetMix * 100.0f)) + "%", juce::dontSendNotification);
}

void MainComponent::applyTheme(Theme theme)
{
    currentTheme = theme;
    switch (theme)
    {
        case Theme::flat:
            palette.background = juce::Colour::fromRGB(0x12, 0x12, 0x12);
            palette.toolbar = juce::Colour::fromRGB(0x1e, 0x1e, 0x1e);
            palette.toolbarHighlight = palette.toolbar.brighter(0.15f);
            palette.panel = juce::Colour::fromRGB(0x24, 0x24, 0x24);
            palette.card = juce::Colour::fromRGB(0x2c, 0x2c, 0x2c);
            palette.cardBorder = juce::Colour::fromRGB(0x44, 0x44, 0x44);
            palette.accent = juce::Colour::fromRGB(0x59, 0xa7, 0xff);
            palette.text = juce::Colours::white;
            palette.muted = juce::Colour::fromRGB(0xbb, 0xbb, 0xbb);
            break;
        case Theme::win98:
            palette.background = juce::Colour::fromRGB(0x00, 0x80, 0x80);
            palette.toolbar = juce::Colour::fromRGB(0xc0, 0xc0, 0xc0);
            palette.toolbarHighlight = juce::Colour::fromRGB(0xdf, 0xdf, 0xdf);
            palette.panel = juce::Colour::fromRGB(0xc0, 0xc0, 0xc0);
            palette.card = juce::Colour::fromRGB(0xdf, 0xdf, 0xdf);
            palette.cardBorder = juce::Colour::fromRGB(0x00, 0x00, 0x00);
            palette.accent = juce::Colour::fromRGB(0x00, 0x00, 0x80);
            palette.text = juce::Colours::black;
            palette.muted = juce::Colour::fromRGB(0x22, 0x22, 0x22);
            break;
        case Theme::winxp:
            palette.background = juce::Colour::fromRGB(0xd6, 0xe6, 0xff);
            palette.toolbar = juce::Colour::fromRGB(0xf4, 0xf8, 0xff);
            palette.toolbarHighlight = juce::Colour::fromRGB(0xd7, 0xe6, 0xff);
            palette.panel = juce::Colour::fromRGB(0xe7, 0xf0, 0xff);
            palette.card = juce::Colour::fromRGB(0xf6, 0xf9, 0xff);
            palette.cardBorder = juce::Colour::fromRGB(0x6e, 0x8e, 0xd1);
            palette.accent = juce::Colour::fromRGB(0x2b, 0x63, 0xe6);
            palette.text = juce::Colour::fromRGB(0x00, 0x17, 0x4a);
            palette.muted = juce::Colour::fromRGB(0x27, 0x42, 0x76);
            break;
    }

    titleLabel.setColour(juce::Label::textColourId, palette.text);
    chainTitleLabel.setColour(juce::Label::textColourId, palette.text);
    mixLabel.setColour(juce::Label::textColourId, palette.text);
    mixValueLabel.setColour(juce::Label::textColourId, palette.text);
    latencyLabel.setColour(juce::Label::textColourId, palette.muted);
    emptyLabel.setColour(juce::Label::textColourId, palette.muted);

    auto styleButton = [this](juce::Button& b)
    {
        b.setColour(juce::TextButton::buttonColourId, palette.card);
        b.setColour(juce::TextButton::textColourOff, palette.text);
        b.setColour(juce::TextButton::textColourOn, palette.text);
        b.setColour(juce::TextButton::buttonOnColourId, palette.accent.withAlpha(0.65f));
    };

    styleButton(startAudioButton);
    styleButton(addStreamTopButton);
    styleButton(editToggleButton);
    styleButton(styleModeButton);
    styleButton(saveButton);
    styleButton(loadButton);
    styleButton(scanButton);
    styleButton(addStreamButton);
    styleButton(bankButton);

    mixSlider.setColour(juce::Slider::trackColourId, palette.accent);
    mixSlider.setColour(juce::Slider::thumbColourId, palette.accent.brighter(0.2f));
    mixSlider.setColour(juce::Slider::backgroundColourId, palette.card);

    themePicker.setColour(juce::ComboBox::backgroundColourId, palette.card);
    themePicker.setColour(juce::ComboBox::textColourId, palette.text);
    themePicker.setColour(juce::ComboBox::outlineColourId, palette.cardBorder);

    if (auto* vs = workspaceViewport.getVerticalScrollBar())
    {
        vs->setColour(juce::ScrollBar::thumbColourId, palette.accent.withAlpha(0.6f));
        vs->setColour(juce::ScrollBar::trackColourId, palette.panel);
    }

    for (auto& comp : slotComponents)
    {
        comp->refreshTheme();
        comp->repaint();
    }

    repaint();
}

void MainComponent::updateThemeButtonStates()
{
    editToggleButton.setToggleState(editMode, juce::dontSendNotification);
    editToggleButton.setButtonText(editMode ? "✏️ Edit: ON" : "✏️ Edit: OFF");
    styleModeButton.setToggleState(styleMode, juce::dontSendNotification);
    styleModeButton.setButtonText(styleMode ? "🎨 Style Mode: ON" : "🎨 Style Mode: OFF");

    chainTitleLabel.setText("Block " + session.activeBank + " — Active Bank", juce::dontSendNotification);
    bankButton.setButtonText(session.activeBank == "A" ? "Switch to Bank B" : "Switch to Bank A");
    addStreamButton.setButtonText(session.activeBank == "A" ? "Add Stream to Bank A" : "Add Stream to Bank B");
    emptyLabel.setText("Bank " + session.activeBank + " has no plug-ins. Use \"Add Stream\" to insert one.", juce::dontSendNotification);
}

void MainComponent::startAudioEngine()
{
    deviceManager.restartLastAudioDevice();
    startAudioButton.setButtonText("🎵 Restart Audio");
}

juce::String MainComponent::slotDisplayName(const PluginSlotState& slot) const
{
    juce::File f(slot.pluginID);
    if (f.existsAsFile())
        return f.getFileNameWithoutExtension();
    if (slot.pluginID.containsChar('/') || slot.pluginID.containsChar('\'))
        return juce::File::createFileWithoutCheckingPath(slot.pluginID).getFileNameWithoutExtension();
    return slot.pluginID;
}
