# Judge hand-check (T16)

Ten judge verdicts from the dev split (judge `databricks-claude-sonnet-4-6`), for a person to confirm.

| Question | Judge | Verdict | Rationale (start) |
|---|---|---|---|
| G01 | correctness | yes | The question asks how quickly a SEV2 payment incident must be acknowledged. The claim states "30 minutes." The document explicitly states that "A SEV2 incident (one acquirer degrad |
| G03 | correctness | yes | The question asks how long quarantined payment rows are retained. The claim states "90 days." The document explicitly states "Quarantined payment rows are retained for 90 days [DOC |
| G05 | correctness | yes | The question asks after how many hours a merchant payout hold auto-releases. The claim states it auto-releases after 72 hours. The document explicitly states "A merchant payout hol |
| G07 | correctness | yes | The question asks how quickly a personal data deletion request must be completed. The claim states it must be completed within 30 days. The document explicitly states: "Personal da |
| G09 | correctness | yes | The question asks which PagerDuty schedule to page before starting RB-014. The claim states "payops-primary." The document explicitly states "That is the PagerDuty schedule payops- |
| G11 | correctness | yes | The question asks about the merchant discount rate for card payments through acq_3. The claim states it is 2.10% + SGD 0.25. The document explicitly states "The card merchant disco |
| G13 | correctness | yes | The claim states that Meridian can claim "a service credit of 10% of the month's processing fees" when acq_7 breaches its SLA. The document explicitly states: "Meridian may claim a |
| G14 | correctness | yes | The question asks how quickly Finance must be told about an acq_7 SLA breach. The claim states "notified within 24 hours." The document states "Meridian Finance must be notified wi |
| G17 | correctness | yes | The question asks about Singapore's current GST rate. The document states "I don't have that in the knowledge base." The claim states that the assistant says the knowledge base doe |
| G19 | correctness | yes | The question asks when Meridian loyalty points expire. The document explicitly states "I don't have that in the knowledge base," indicating that the information about Meridian loya |
