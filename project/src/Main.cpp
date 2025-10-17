
#include <juce_gui_extra/juce_gui_extra.h>
#include "MainComponent.h"
class AmbianceHostApplication : public juce::JUCEApplication{
public:
  const juce::String getApplicationName() override { return "AmbianceHost"; }
  const juce::String getApplicationVersion() override { return "0.3"; }
  bool moreThanOneInstanceAllowed() override { return true; }
  void initialise(const juce::String&) override { mainWindow.reset(new MainWindow(getApplicationName())); }
  void shutdown() override { mainWindow = nullptr; }
  void systemRequestedQuit() override { quit(); }
  class MainWindow: public juce::DocumentWindow{
  public:
    MainWindow(juce::String name): DocumentWindow(name,
      juce::Desktop::getInstance().getDefaultLookAndFeel().findColour(ResizableWindow::backgroundColourId),
      DocumentWindow::allButtons){
      setUsingNativeTitleBar(true);
      setContentOwned(new MainComponent(), true);
      centreWithSize(980, 680);
      setVisible(true);
    }
    void closeButtonPressed() override { JUCEApplication::getInstance()->systemRequestedQuit(); }
  };
private: std::unique_ptr<MainWindow> mainWindow;
};
START_JUCE_APPLICATION(AmbianceHostApplication)
