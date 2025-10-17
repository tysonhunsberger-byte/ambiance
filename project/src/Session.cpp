
#include "Session.h"
#include <juce_data_structures/juce_data_structures.h>

static juce::var slotToVar(const PluginSlotState& s){
  juce::DynamicObject::Ptr o=new juce::DynamicObject();
  o->setProperty("pluginID", s.pluginID);
  o->setProperty("format", s.format);
  o->setProperty("state", s.state.toBase64Encoding());
  o->setProperty("bypassed", s.bypassed);
  return juce::var(o.get());
}
static bool slotFromVar(const juce::var& v, PluginSlotState& out){
  if(!v.isObject()) return false; auto* o=v.getDynamicObject();
  out.pluginID=o->getProperty("pluginID").toString();
  out.format=o->getProperty("format").toString();
  out.state.fromBase64Encoding(o->getProperty("state").toString());
  out.bypassed=(bool)o->getProperty("bypassed");
  return true;
}
static juce::var chainToVar(const ChainState& c){
  juce::DynamicObject::Ptr o=new juce::DynamicObject();
  juce::Array<juce::var> arr; for(auto& s: c.slots) arr.add(slotToVar(s));
  o->setProperty("slots", juce::var(arr)); o->setProperty("wetMix", c.wetMix);
  return juce::var(o.get());
}
static bool chainFromVar(const juce::var& v, ChainState& out){
  if(!v.isObject()) return false; auto* o=v.getDynamicObject();
  out.wetMix=(float)o->getProperty("wetMix");
  out.slots.clear();
  auto* arr=o->getProperty("slots").getArray();
  if(arr) for(auto& it:*arr){ PluginSlotState s; if(slotFromVar(it,s)) out.slots.add(std::move(s)); }
  return true;
}
juce::var SessionIO::toVar(const SessionState& s){
  juce::DynamicObject::Ptr o=new juce::DynamicObject();
  o->setProperty("A", chainToVar(s.bankA)); o->setProperty("B", chainToVar(s.bankB));
  o->setProperty("active", s.activeBank); return juce::var(o.get());
}
bool SessionIO::fromVar(const juce::var& v, SessionState& out){
  if(!v.isObject()) return false; auto* o=v.getDynamicObject();
  chainFromVar(o->getProperty("A"), out.bankA);
  chainFromVar(o->getProperty("B"), out.bankB);
  out.activeBank=o->getProperty("active").toString();
  return true;
}
bool SessionIO::saveToFile(const juce::File& f, const SessionState& s){
  return f.replaceWithText(juce::JSON::toString(toVar(s), true));
}
bool SessionIO::loadFromFile(const juce::File& f, SessionState& s){
  auto txt=f.loadFileAsString(); juce::var v=juce::JSON::parse(txt); return fromVar(v,s);
}
