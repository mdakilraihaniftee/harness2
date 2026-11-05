# Experiment 0: task discovery and selection

Selection used seed 17 and the pre-registered domain-first rule in `task_inventory.json`.
No outcome, hypothesis fit, or prior score entered sampling. No sampled task failed dependency
inspection, so no replacement was made.

| Benchmark | Task ID | Domain | Classification | Source files | Requested deliverable examples | Prior rollout |
|---|---|---|---|---:|---|---|
| jb | `data_entry_keyers/task1` | data_entry_keyers | NATIVE_DETERMINISTIC | 16 | Compliance_Checklist.xlsx, Customer_Master_List.csv | no |
| jb | `secretaries_and_administrative_assistants_except_legal_medical_and_executive/task1` | secretaries_and_administrative_assistants_except_legal_medical_and_executive | NATIVE_DETERMINISTIC | 7 | Donor_Database_Template.xlsx, Heartland_Donor_Database_Q4_Reconciled.xlsx | no |
| jb | `purchasing_agents_except_wholesale_retail_and_farm_products/task2` | purchasing_agents_except_wholesale_retail_and_farm_products | NATIVE_DETERMINISTIC | 7 | bid_evaluation_matrix_template.xlsx, department_requisition.xlsx | no |
| jb | `sociology_teachers_postsecondary/task1` | sociology_teachers_postsecondary | NATIVE_DETERMINISTIC | 5 | Effective_Advising_Practice_Guide.pdf, Holistic_Intervention_Plan.docx | no |
| jb | `court_clerks/task1` | court_clerks | NATIVE_DETERMINISTIC | 6 | Arkansas_Sentencing_Order_Form.pdf, Defense_Plea_Memo_Simmons.pdf | no |
| jb | `financial_managers_branch_or_department/task2` | financial_managers_branch_or_department | NATIVE_DETERMINISTIC | 4 | Enhanced Quarterly Risk Report (Excel .xlsx, loan_risk_rating_sheet.xls | no |
| lab | `bankruptcy-restructuring/draft-restructuring-support-agreement` | bankruptcy-restructuring | NATIVE_DETERMINISTIC | 8 | restructuring-support-agreement.docx | no |
| lab | `intellectual-property/draft-responses-to-discovery-requests` | intellectual-property | NATIVE_DETERMINISTIC | 8 | interrogatory-responses.docx, rfp-responses.docx | no |
| lab | `trusts-estates-private-client/draft-motion-for-temporary-orders` | trusts-estates-private-client | NATIVE_DETERMINISTIC | 7 | motion-for-temporary-orders.docx | no |
| lab | `healthcare-life-sciences/draft-enterprise-saas-vendor-onboarding-due-diligence` | healthcare-life-sciences | NATIVE_DETERMINISTIC | 7 | vendor-onboarding-questionnaire.docx | no |
| lab | `data-privacy-cybersecurity/draft-response-to-regulatory-inquiry-letter` | data-privacy-cybersecurity | NATIVE_DETERMINISTIC | 7 | ag-response-letter.docx, client-advisory-memo.docx | no |
| lab | `capital-markets/draft-markup-of-underwriting-agreement` | capital-markets | NATIVE_DETERMINISTIC | 6 | marked-up-underwriting-agreement.docx | no |

`NATIVE_DETERMINISTIC` means only that file existence, filename/extension, container
parseability, or another meaningful part of the original output contract can be checked
offline. Every sampled task still requires its external LLM judge for full semantic
correctness. Benchmark-derived schema/API interventions are written only into new research
harnesses; installed benchmark bytes remain unchanged and are verified by SHA-256.
