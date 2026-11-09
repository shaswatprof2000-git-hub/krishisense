"""Farmer-facing alert text in Odia, Hindi and English.

Keep messages short, concrete and in the farmer's units (minutes of pump time).
Have the Odia and Hindi text reviewed by a native speaker from the area before
going live; local words for irrigation and pump vary between districts.
"""
from __future__ import annotations

from .advisor import IRRIGATE_NOW, IRRIGATE_SOON, NO_DATA, OK, SENSOR_STALE, SKIP_RAIN, Advice

TEMPLATES = {
    "or": {
        IRRIGATE_NOW: "🌱 {name}: ଜଳସେଚନ ଦରକାର। ଆଜି ପମ୍ପ {minutes} ମିନିଟ୍ ଚଲାନ୍ତୁ। ମାଟି ଆର୍ଦ୍ରତା: {water}%",
        IRRIGATE_SOON: "🌱 {name}: କାଲି ସକାଳେ ପମ୍ପ ପ୍ରାୟ {minutes} ମିନିଟ୍ ଚଲାନ୍ତୁ। ଆଜି ଜଳସେଚନ ଦରକାର ନାହିଁ।",
        SKIP_RAIN: "🌧️ {name}: ଜଳସେଚନ କରନ୍ତୁ ନାହିଁ। ଆଗାମୀ 24 ଘଣ୍ଟାରେ ପ୍ରାୟ {rain} ମିମି ବର୍ଷା ହେବାର ସମ୍ଭାବନା ({prob}%)।",
        OK: "✅ {name}: ମାଟିରେ ଯଥେଷ୍ଟ ଆର୍ଦ୍ରତା ଅଛି ({water}%)। ଆଜି ଜଳସେଚନ ଦରକାର ନାହିଁ।",
        SENSOR_STALE: "⚠️ {name}: {hours} ଘଣ୍ଟା ହେଲା ସେନ୍ସରରୁ ତଥ୍ୟ ମିଳୁନାହିଁ। ବ୍ୟାଟେରି ଓ ସଂଯୋଗ ଯାଞ୍ଚ କରନ୍ତୁ।",
        NO_DATA: "⚠️ {name}: ସେନ୍ସରରୁ ଏପର୍ଯ୍ୟନ୍ତ କୌଣସି ତଥ୍ୟ ମିଳିନାହିଁ।",
        "urgent": "⚠️ ଜରୁରୀ — ",
        "battery": " 🔋 ବ୍ୟାଟେରି କମ୍।",
    },
    "hi": {
        IRRIGATE_NOW: "🌱 {name}: सिंचाई ज़रूरी है। आज पंप {minutes} मिनट चलाएँ। मिट्टी की नमी: {water}%",
        IRRIGATE_SOON: "🌱 {name}: कल सुबह पंप लगभग {minutes} मिनट चलाएँ। आज सिंचाई की ज़रूरत नहीं।",
        SKIP_RAIN: "🌧️ {name}: सिंचाई न करें। अगले 24 घंटों में लगभग {rain} मिमी बारिश की संभावना ({prob}%)।",
        OK: "✅ {name}: मिट्टी में पर्याप्त नमी है ({water}%)। आज सिंचाई की ज़रूरत नहीं।",
        SENSOR_STALE: "⚠️ {name}: {hours} घंटे से सेंसर से डेटा नहीं मिला। बैटरी और कनेक्शन जाँचें।",
        NO_DATA: "⚠️ {name}: सेंसर से अभी तक कोई डेटा नहीं मिला।",
        "urgent": "⚠️ तुरंत — ",
        "battery": " 🔋 बैटरी कम है।",
    },
    "en": {
        IRRIGATE_NOW: "🌱 {name}: Irrigation needed. Run the pump for {minutes} minutes today. Soil water: {water}%",
        IRRIGATE_SOON: "🌱 {name}: Run the pump for about {minutes} minutes tomorrow morning. No irrigation needed today.",
        SKIP_RAIN: "🌧️ {name}: Don't irrigate. About {rain} mm of rain is likely in the next 24 hours ({prob}%).",
        OK: "✅ {name}: Soil has enough water ({water}%). No irrigation needed today.",
        SENSOR_STALE: "⚠️ {name}: No sensor data for {hours} hours. Check the battery and connection.",
        NO_DATA: "⚠️ {name}: No data received from the sensor yet.",
        "urgent": "⚠️ URGENT — ",
        "battery": " 🔋 Battery low.",
    },
}


def render(advice: Advice, station_name: str, language: str = "or") -> str:
    t = TEMPLATES.get(language, TEMPLATES["en"])
    text = t[advice.status].format(
        name=station_name,
        minutes=advice.pump_minutes,
        water=int(advice.available_water_pct) if advice.available_water_pct is not None else "?",
        rain=advice.rain_next_24h_mm,
        prob=int(advice.rain_prob_pct),
        hours=int(advice.hours_since_reading or 0),
    )
    if advice.urgent:
        text = t["urgent"] + text
    if any(n.startswith("battery low") for n in advice.notes):
        text += t["battery"]
    return text
