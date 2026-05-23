"""
Drafts flagged for regeneration — fabricated claims cannot be fixed surgically.
Run this list through the personalization engine to regenerate clean step-2 bodies.

Generated: 2026-05-13T23:01:21.287360+00:00
"""

REGENERATE_DRAFT_IDS = [
    "b7868413-0eb2-45d7-8a1d-fcfee88f5054",
    "6a2c7a60-7f5c-4ddc-8ab2-79b4cc9ddbc0"
]

REGENERATE_CONTEXT = [
    {
        "draft_id": "b7868413-0eb2-45d7-8a1d-fcfee88f5054",
        "company": "American Fuji Seal",
        "contact": "Ezra Bowen",
        "contact_id": "228fe282-8901-4db6-a016-e81b3532362a",
        "company_id": "328ff864-66bf-4d6a-ab2f-f6d4dcc1360f",
        "rejection_reason": "auto_rejected|past_customer_claim:\"we've trained our\"",
        "rejection_category": "FABRICATED_CLAIM",
        "sequence_step": 2,
        "sequence_name": "email_value_first"
    },
    {
        "draft_id": "6a2c7a60-7f5c-4ddc-8ab2-79b4cc9ddbc0",
        "company": "BAUER COMPRESSORS INC.",
        "contact": "Domonic Bell",
        "contact_id": "81ec83df-726a-4859-9443-5196f58e9196",
        "company_id": "49642683-872f-4e9c-8c3f-ce0ac7faca25",
        "rejection_reason": "auto_rejected|fabricated_anecdote:'a manufacturer where'",
        "rejection_category": "FABRICATED_CLAIM",
        "sequence_step": 2,
        "sequence_name": "email_value_first"
    }
]
