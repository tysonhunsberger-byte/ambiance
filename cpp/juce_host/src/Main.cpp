#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_audio_utils/juce_audio_utils.h>
#include <juce_gui_extra/juce_gui_extra.h>

namespace
{

constexpr int defaultWidth = 900;
constexpr int defaultHeight = 600;

class PluginComponent : public juce::Component,
                        private juce::Timer
{
public:
    explicit PluginComponent(const juce::File& pluginFile)
    {
        if (!pluginFile.existsAsFile())
        {
            errorMessage = "Plugin file does not exist: " + pluginFile.getFullPathName();
            return;
        }

        formatManager.addDefaultFormats();

        juce::PluginDescription description;
        description.fileOrIdentifier = pluginFile.getFullPathName();
        description.pluginFormatName = "VST3";
        description.name = pluginFile.getFileNameWithoutExtension();
        description.descriptiveName = description.name;
        description.manufacturerName = "Unknown";
        description.category = "Instrument";

        juce::String error;
        instance.reset(formatManager.createPluginInstance(description, 48000.0, 512, error));

        if (instance == nullptr)
        {
            errorMessage = error.isNotEmpty() ? error : juce::String("Unable to create plugin instance.");
            return;
        }

        auto* processor = instance->getProcessor();
        if (processor == nullptr)
        {
            errorMessage = "Plugin has no processor.";
            instance.reset();
            return;
        }

        deviceManager.initialiseWithDefaultDevices(0, processor->getTotalNumOutputChannels());
        deviceManager.addAudioCallback(&player);
        deviceManager.addMidiInputCallback({}, &player);
        player.setProcessor(processor);

        editor.reset(processor->createEditor());
        if (editor == nullptr)
        {
            errorMessage = "Plugin does not provide a UI editor.";
            return;
        }

        addAndMakeVisible(editor.get());
        setSize(editor->getWidth(), editor->getHeight());
        startTimerHz(30);
    }

    ~PluginComponent() override
    {
        stopTimer();
        player.setProcessor(nullptr);
        deviceManager.removeMidiInputCallback({}, &player);
        deviceManager.removeAudioCallback(&player);
        editor.reset();
        instance.reset();
    }

    bool isValid() const noexcept { return instance != nullptr && editor != nullptr && errorMessage.isEmpty(); }

    juce::String getError() const { return errorMessage; }

    void resized() override
    {
        if (editor != nullptr)
            editor->setBounds(getLocalBounds());
    }

private:
    void timerCallback() override
    {
        if (editor == nullptr)
            return;

        const auto bounds = getLocalBounds();
        if (bounds.getWidth() != editor->getWidth() || bounds.getHeight() != editor->getHeight())
            setSize(editor->getWidth(), editor->getHeight());
    }

    juce::AudioPluginFormatManager formatManager;
    std::unique_ptr<juce::AudioPluginInstance> instance;
    std::unique_ptr<juce::AudioProcessorEditor> editor;
    juce::AudioDeviceManager deviceManager;
    juce::AudioProcessorPlayer player;
    juce::String errorMessage;
};

class MainWindow : public juce::DocumentWindow
{
public:
    MainWindow(const juce::String& title, const juce::File& plugin)
        : DocumentWindow(title,
                         juce::Desktop::getInstance().getDefaultLookAndFeel().findColour(juce::ResizableWindow::backgroundColourId),
                         DocumentWindow::allButtons)
    {
        setUsingNativeTitleBar(true);
        setResizable(true, false);
        setVisible(true);

        auto component = std::make_unique<PluginComponent>(plugin);
        if (!component->isValid())
        {
            juce::AlertWindow::showMessageBoxAsync(juce::MessageBoxIconType::WarningIcon,
                                                   "Unable to load plugin",
                                                   component->getError());
            setContentOwned(new juce::Component(), true);
            centreWithSize(defaultWidth, defaultHeight);
            return;
        }

        auto width = juce::jmax(component->getWidth(), defaultWidth);
        auto height = juce::jmax(component->getHeight(), defaultHeight);
        setContentOwned(component.release(), true);
        centreWithSize(width, height);
    }

    void closeButtonPressed() override
    {
        juce::JUCEApplication::getInstance()->systemRequestedQuit();
    }
};

class HostApplication : public juce::JUCEApplication
{
public:
    HostApplication() = default;

    const juce::String getApplicationName() override { return "Ambiance JUCE Plugin Host"; }
    const juce::String getApplicationVersion() override { return "0.1.0"; }

    void initialise(const juce::String& commandLine) override
    {
        juce::File pluginFile;

        if (commandLine.isNotEmpty())
        {
            pluginFile = juce::File::getCurrentWorkingDirectory().getChildFile(commandLine.trim());
            if (!pluginFile.existsAsFile())
                pluginFile = juce::File(commandLine.trim());
        }

        if (!pluginFile.existsAsFile())
        {
            juce::FileChooser chooser("Select a VST3 plugin to load",
                                      juce::File::getSpecialLocation(juce::File::userHomeDirectory),
                                      "*.vst3");
            if (!chooser.browseForFileToOpen())
            {
                juce::JUCEApplication::quit();
                return;
            }
            pluginFile = chooser.getResult();
        }

        mainWindow = std::make_unique<MainWindow>(getApplicationName(), pluginFile);
    }

    void shutdown() override { mainWindow.reset(); }

private:
    std::unique_ptr<MainWindow> mainWindow;
};

} // namespace

START_JUCE_APPLICATION(HostApplication)

