// Generated from canonical Python fixtures and replay proposals. Browser simulation only.
const ALLERGUARD_DEMO_DATA = {
  "business": {
    "business_id": "demo-cafe",
    "name": "The Walnut & Whisk Caf\u00e9 (fictional demo)",
    "inventory": [
      {
        "name": "Walnut brownie",
        "kind": "product",
        "ingredients": [
          "walnut",
          "wheat flour",
          "egg",
          "milk"
        ],
        "allergens": [
          "cereals containing gluten",
          "eggs",
          "milk",
          "tree nuts"
        ],
        "brand": "Walnut & Whisk",
        "supplier": "Fictional Bakery Supplier",
        "categories": [],
        "batch_codes": []
      },
      {
        "name": "Doritos Chilli Heatwave",
        "kind": "product",
        "ingredients": [
          "maize",
          "seasoning",
          "milk"
        ],
        "allergens": [
          "milk"
        ],
        "brand": "PepsiCo",
        "supplier": null,
        "categories": [],
        "batch_codes": []
      }
    ],
    "handled_allergens": [
      "cereals containing gluten",
      "eggs",
      "milk",
      "mustard",
      "tree nuts"
    ]
  },
  "alerts": [
    {
      "id": "FSA-PRIN-43-2026",
      "title": "Sainsbury\u2019s recalls Inspired to Cook by Sainsbury\u2019s Pitted Black Olives because of contamination with Listeria monocytogenes",
      "tier": "NO_MATCH",
      "decision": "SILENT",
      "reason": "No product, ingredient, allergen, supplier, or category link was found in the recorded inventory.",
      "alert_url": "https://alerts.food.gov.uk/news-alerts/alert/fsa-prin-43-2026",
      "modified": "2026-09-04T18:39:45.509000+00:00"
    },
    {
      "id": "FSA-PRIN-39-2026",
      "title": "A.Vogel Ltd recalls Rapunzel bioSnacky Das Original Red Clover \u2013 Seeds for Sprouts and Seedlings because of contamination with E. coli (STEC)",
      "tier": "NO_MATCH",
      "decision": "SILENT",
      "reason": "No product, ingredient, allergen, supplier, or category link was found in the recorded inventory.",
      "alert_url": "https://alerts.food.gov.uk/news-alerts/alert/fsa-prin-39-2026",
      "modified": "2026-08-10T15:49:00.442000+00:00"
    },
    {
      "id": "FSA-AA-55-2020",
      "title": "Waitrose & Partners recalls Chocolate Mini Cupcakes 9s because of undeclared walnuts",
      "tier": "POSSIBLE",
      "decision": "ESCALATE",
      "reason": "The alert concerns tree nuts, which your business handles, but the recalled product is not recorded in inventory.",
      "alert_url": "https://www.food.gov.uk/news-alerts/alert/fsa-aa-55-2020",
      "modified": "2020-09-17T16:47:41.292000+00:00",
      "action_pack": {
        "pull": "Check potentially affected stock against Waitrose & Partners recalls Chocolate Mini Cupcakes 9s because of undeclared walnuts; isolate it pending review.",
        "staff_note": "Do not sell potentially affected items linked to Waitrose & Partners recalls Chocolate Mini Cupcakes 9s because of undeclared walnuts until checked.",
        "customer_notice": "DRAFT ONLY \u2014 NOT SENT \u2014 AWAITING OWNER APPROVAL: reviewing Waitrose & Partners recalls Chocolate Mini Cupcakes 9s because of undeclared walnuts.",
        "substitution": "No substitution suggested."
      }
    },
    {
      "id": "FSA-AA-42-2026",
      "title": "Tesco recalls Tesco Finest Caesar & Smoked Bacon Coleslaw because of undeclared mustard",
      "tier": "POSSIBLE",
      "decision": "ESCALATE",
      "reason": "The alert concerns mustard, which your business handles, but the recalled product is not recorded in inventory.",
      "alert_url": "https://alerts.food.gov.uk/news-alerts/alert/fsa-aa-42-2026",
      "modified": "2026-09-03T16:11:41.515000+00:00",
      "action_pack": {
        "pull": "Check potentially affected stock against Tesco recalls Tesco Finest Caesar & Smoked Bacon Coleslaw because of undeclared mustard; isolate it pending review.",
        "staff_note": "Do not sell potentially affected items linked to Tesco recalls Tesco Finest Caesar & Smoked Bacon Coleslaw because of undeclared mustard until checked.",
        "customer_notice": "DRAFT ONLY \u2014 NOT SENT \u2014 AWAITING OWNER APPROVAL: reviewing Tesco recalls Tesco Finest Caesar & Smoked Bacon Coleslaw because of undeclared mustard.",
        "substitution": "No substitution suggested."
      }
    },
    {
      "id": "FSA-AA-38-2026",
      "title": "PepsiCo recalls Doritos Chilli Heatwave because of undeclared milk",
      "tier": "LIKELY",
      "decision": "ESCALATE",
      "reason": "Recall: Doritos Chilli Heatwave. You stock Doritos Chilli Heatwave, and the recall is batch-limited: your recorded stock batch for Doritos Chilli Heatwave is unknown. Check the exact batch and best-before details before selling it.",
      "alert_url": "https://alerts.food.gov.uk/news-alerts/alert/fsa-aa-38-2026",
      "modified": "2026-07-17T20:16:28.573000+00:00",
      "action_pack": {
        "pull": "Check potentially affected stock against PepsiCo recalls Doritos Chilli Heatwave because of undeclared milk; isolate it pending review.",
        "staff_note": "Do not sell potentially affected items linked to PepsiCo recalls Doritos Chilli Heatwave because of undeclared milk until checked.",
        "customer_notice": "DRAFT ONLY \u2014 NOT SENT \u2014 AWAITING OWNER APPROVAL: reviewing PepsiCo recalls Doritos Chilli Heatwave because of undeclared milk.",
        "substitution": "No substitution suggested."
      }
    }
  ]
};
