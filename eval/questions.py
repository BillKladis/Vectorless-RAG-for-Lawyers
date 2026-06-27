"""
Gold-standard evaluation set for the Cloud Service Agreement.

Each item was written by reading the actual contract text. ``expected_sections``
are the clause numbers a competent associate would cite; ``key_facts`` are the
propositions a correct answer must contain. These drive ``evaluate.py``.
"""

CSA_QUESTIONS = [
    {
        "id": "liability_cap",
        "question": "What is each party's cap on liability, and what claims are excluded from the cap?",
        "expected_sections": ["8.1", "8.4"],
        "key_facts": [
            "Each party's total liability is capped at the General Cap Amount (§ 8.1(a)).",
            "Increased Claims are capped at the higher Increased Cap Amount (§ 8.1(b)).",
            "Unlimited Claims are not subject to the caps in § 8.1 (§ 8.4).",
            "The damages waiver does not apply to a breach of confidentiality / § 10 (§ 8.4).",
        ],
    },
    {
        "id": "suspension",
        "question": "Under what circumstances can the provider suspend the customer's access?",
        "expected_sections": ["2.2"],
        "key_facts": [
            "An undisputed balance outstanding more than 30 days (§ 2.2).",
            "A breach of the use restrictions in § 2.1 (§ 2.2).",
            "Use that materially and negatively impacts the Product or others (§ 2.2).",
            "Provider may suspend with or without notice but will try to give notice first.",
        ],
    },
    {
        "id": "survival",
        "question": "Which obligations survive expiration or termination of the agreement?",
        "expected_sections": ["5.6"],
        "key_facts": [
            "A list of sections survives, including Payment (§ 4), Limitation of Liability (§ 8), Indemnification (§ 9), and Confidentiality (§ 10) (§ 5.6).",
            "Confidential Information may be retained under standard backup/retention policies, with §§ 3 and 10 continuing to apply (§ 5.6).",
        ],
    },
    {
        "id": "indemnification",
        "question": "Who indemnifies whom, and what must the protected party do to receive indemnification?",
        "expected_sections": ["9.1", "9.2", "9.3"],
        "key_facts": [
            "Provider indemnifies Customer for Provider Covered Claims (§ 9.1).",
            "Customer indemnifies Provider for Customer Covered Claims (§ 9.2).",
            "The protected party must promptly notify, provide reasonable assistance, and give the indemnifying party sole control of defense and settlement (§ 9.3).",
        ],
    },
    {
        "id": "termination_cause",
        "question": "When can a party terminate the agreement for the other party's breach, and is there a cure period?",
        "expected_sections": ["5.3"],
        "key_facts": [
            "Either party may terminate if the other fails to cure a material breach within 30 days of notice (§ 5.3(a)).",
            "Immediate termination is allowed for an incurable material breach, dissolution, assignment for creditors, or insolvency/bankruptcy continuing more than 60 days (§ 5.3(b)).",
        ],
    },
    {
        "id": "force_majeure",
        "question": "What happens if a force majeure event prevents the service from operating?",
        "expected_sections": ["5.4"],
        "key_facts": [
            "Either party may terminate an affected Order Form if a Force Majeure Event prevents the Product from materially operating for 30 or more consecutive days (§ 5.4).",
            "Provider pays a prorated refund of prepaid Fees for the remainder of the Subscription Period (§ 5.4).",
            "Force majeure does not excuse Fees accrued before termination (§ 5.4).",
        ],
    },
    {
        "id": "payment_dispute",
        "question": "How does the customer dispute a charge, and what are the deadlines?",
        "expected_sections": ["4.6"],
        "key_facts": [
            "Customer must notify Provider before payment is due, or within 30 days of an automatic payment (§ 4.6).",
            "Customer must pay all undisputed amounts on time (§ 4.6).",
            "The parties work to resolve the dispute within 15 days (§ 4.6).",
        ],
    },
    {
        "id": "data_deletion",
        "question": "After termination, what happens to the customer's content?",
        "expected_sections": ["5.5"],
        "key_facts": [
            "Upon Customer's request, Provider will delete Customer Content within 60 days (§ 5.5(b)).",
            "Customer loses the right to use the Product, and each Recipient returns or destroys Confidential Information (§ 5.5).",
        ],
    },
    {
        "id": "ml_training",
        "question": "Can the provider use the customer's data to train AI or machine-learning models?",
        "expected_sections": ["1.6"],
        "key_facts": [
            "Usage Data and Customer Content may be used to develop, train, or enhance AI/ML models in the Product (§ 1.6).",
            "The data must be aggregated and the Provider must use commercially reasonable efforts to de-identify it (§ 1.6).",
            "Personal Data obligations under Applicable Data Protection Laws are not reduced (§ 1.6).",
        ],
    },
    {
        "id": "confidentiality_exclusions",
        "question": "What information is excluded from the confidentiality obligations?",
        "expected_sections": ["10.2"],
        "key_facts": [
            "Information that is or becomes public through no fault of the Recipient (§ 10.2).",
            "Information already known to the Recipient without restriction, independently developed, or rightfully received from a third party (§ 10.2).",
        ],
    },
    {
        "id": "governing_law",
        "question": "What law governs the agreement and where must disputes be brought? Are there exceptions for injunctions?",
        "expected_sections": ["12.3", "12.4"],
        "key_facts": [
            "The Governing Law governs and the Chosen Courts have exclusive jurisdiction (§ 12.3).",
            "Despite the forum-selection clause, a party may seek injunctive relief for a breach of confidentiality (§ 10) in any court of competent jurisdiction (§ 12.4).",
        ],
    },
    {
        "id": "feedback_rights",
        "question": "What rights does the provider have over feedback the customer gives?",
        "expected_sections": ["1.4"],
        "key_facts": [
            "Feedback is given AS IS and Provider may use all Feedback freely without restriction or obligation (§ 1.4).",
            "Provider may collect and use Usage Data, but may only disclose it if aggregated and de-identified (§ 1.4).",
        ],
    },
]
