export const LANGUAGES = [
  { id: 'en', label: 'English', native: 'English', symbol: 'A' },
  { id: 'hi', label: 'Hindi', native: 'हिन्दी', symbol: 'अ' },
  { id: 'bho', label: 'Bhojpuri', native: 'भोजपुरी', symbol: 'भ' },
];

const NAV = {
  en: { home: 'Home', new: 'New screening', patients: 'Patients', history: 'History', sync: 'Sync queue', phc: 'PHC dashboard', architecture: 'Pipeline & architecture', model: 'Model & data audit', settings: 'Settings' },
  hi: { home: 'होम', new: 'नई स्क्रीनिंग', patients: 'मरीज़', history: 'इतिहास', sync: 'सिंक कतार', phc: 'PHC डैशबोर्ड', architecture: 'पाइपलाइन', model: 'मॉडल व डेटा', settings: 'सेटिंग्स' },
  bho: { home: 'होम', new: 'नया स्क्रीनिंग', patients: 'मरीज़', history: 'पुरान रिकार्ड', sync: 'सिंक कतार', phc: 'PHC डैशबोर्ड', architecture: 'पाइपलाइन', model: 'मॉडल आ डेटा', settings: 'सेटिंग' },
};

const COUNSEL = {
  maternal_anemia: {
    en: {
      summary: 'This is a synthetic prototype estimate, not a laboratory result or diagnosis.',
      risk: 'The demo category is a software demonstration tag only. It is not a clinical risk classification.',
      script: 'Please arrange confirmation with the appropriate health-centre test and follow local maternal-care protocol. A clinician should review the result.',
      action: 'Confirm with appropriate clinical testing; follow the local maternal-health protocol and clinician advice.',
      safety: 'Do not use this demo value to start, stop, or change treatment.',
    },
    hi: {
      summary: 'यह केवल एक कृत्रिम प्रोटोटाइप अनुमान है, लैब रिपोर्ट या निदान नहीं।',
      risk: 'डेमो श्रेणी केवल सॉफ्टवेयर प्रदर्शन के लिए है; यह चिकित्सकीय जोखिम वर्गीकरण नहीं है।',
      script: 'कृपया स्वास्थ्य केंद्र में उपयुक्त जांच से इसकी पुष्टि कराएं और स्थानीय मातृ-स्वास्थ्य प्रोटोकॉल का पालन करें। स्वास्थ्यकर्मी/चिकित्सक से चर्चा करें।',
      action: 'उपयुक्त जांच से पुष्टि करें और स्थानीय मातृ-स्वास्थ्य प्रोटोकॉल व चिकित्सक की सलाह का पालन करें।',
      safety: 'इस डेमो मान के आधार पर दवा शुरू, बंद या बदलें नहीं।',
    },
    bho: {
      summary: 'ई खाली डेमो खातिर बनावल अंदाजा बा, लैब रिपोर्ट भा पक्का निदान नइखे।',
      risk: 'डेमो के श्रेणी खाली सॉफ्टवेयर देखावे खातिर बा; ई असली मेडिकल जोखिम के फैसला नइखे।',
      script: 'कृपया स्वास्थ्य केंद्र पर जरूरी जांच कराके पुष्टि कराईं आ स्थानीय मातृ-स्वास्थ्य नियम मानीं। डॉक्टर भा स्वास्थ्यकर्मी से बात करीं।',
      action: 'उचित जांच से पुष्टि कराईं आ स्थानीय मातृ-स्वास्थ्य नियम आ डॉक्टर के सलाह मानीं।',
      safety: 'एह डेमो मान के आधार पर दवाई शुरू, बंद भा बदलीं मत।',
    },
  },
  neonatal_jaundice: {
    en: {
      summary: 'This is a synthetic prototype estimate, not a serum bilirubin result or diagnosis.',
      risk: 'Newborn review depends on age in hours, gestational age, symptoms, and local protocol. This demo does not calculate a treatment threshold.',
      script: 'Please arrange prompt review by a qualified clinician and confirm with the appropriate test. Follow the newborn-care protocol for the infant’s exact age and condition.',
      action: 'Seek clinician review and confirm with appropriate bilirubin testing under local newborn-care protocol.',
      safety: 'Do not use this demo value to delay care or decide treatment.',
    },
    hi: {
      summary: 'यह केवल कृत्रिम प्रोटोटाइप अनुमान है, सीरम बिलीरुबिन रिपोर्ट या निदान नहीं।',
      risk: 'नवजात की समीक्षा उम्र (घंटों में), गर्भकाल, लक्षण और स्थानीय प्रोटोकॉल पर निर्भर करती है। यह डेमो उपचार सीमा नहीं बताता।',
      script: 'कृपया योग्य चिकित्सक से शीघ्र समीक्षा कराएं और उपयुक्त जांच से पुष्टि करें। शिशु की सही उम्र और स्थिति के अनुसार स्थानीय नवजात-देखभाल प्रोटोकॉल अपनाएं।',
      action: 'चिकित्सक से समीक्षा कराएं और स्थानीय नवजात प्रोटोकॉल के अनुसार उपयुक्त बिलीरुबिन जांच से पुष्टि करें।',
      safety: 'इस डेमो मान के कारण देखभाल में देरी न करें और इससे उपचार तय न करें।',
    },
    bho: {
      summary: 'ई खाली कृत्रिम डेमो के अंदाजा बा, सीरम बिलीरुबिन जांच भा निदान नइखे।',
      risk: 'नवजात के जांच ओकरा उमिर (घंटा में), जनम के समय, लक्षण आ स्थानीय नियम पर निर्भर बा। ई डेमो इलाज के सीमा नइखे बतावत।',
      script: 'कृपया बच्चा के योग्य डॉक्टर से जल्दी देखाईं आ उचित जांच से पुष्टि कराईं। बच्चा के सही उमिर आ हालत के हिसाब से स्थानीय नवजात देखभाल नियम मानीं।',
      action: 'डॉक्टर से समीक्षा कराईं आ स्थानीय नवजात नियम के अनुसार बिलीरुबिन जांच से पुष्टि कराईं।',
      safety: 'एह डेमो मान के चलते इलाज में देरी मत करीं आ दवाई के फैसला एहसे मत लीं।',
    },
  },
};

export function navLabels(language = 'en') { return NAV[language] || NAV.en; }
export function localCounsel(screeningType, language = 'en') {
  const lang = ['en', 'hi', 'bho'].includes(language) ? language : 'en';
  return COUNSEL[screeningType]?.[lang] || COUNSEL.maternal_anemia.en;
}
export function languageName(language) { return LANGUAGES.find((x) => x.id === language)?.label || 'English'; }
