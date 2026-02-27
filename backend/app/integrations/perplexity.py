"""Perplexity API client for ProspectIQ.

Used by the Research Agent for deep company research with live web search.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

PERPLEXITY_BASE_URL = "https://api.perplexity.ai"


class PerplexityClient:
    """Perplexity API client for web-grounded research."""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.perplexity_api_key
        if not self.api_key:
            raise ValueError("PERPLEXITY_API_KEY must be set in .env")
        self.client = httpx.Client(
            base_url=PERPLEXITY_BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=120.0,  # Research queries can take time
        )

    def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = "sonar-pro",
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> dict:
        """Call Perplexity chat completions API.

        Args:
            system_prompt: System-level instructions for the research.
            user_prompt: The specific research query.
            model: Perplexity model (sonar-pro for deep research).
            temperature: Sampling temperature (low for factual research).
            max_tokens: Maximum response tokens.

        Returns:
            Dict with 'content' (response text), 'model', 'usage' (token counts).
        """
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            # Extract response content and usage
            choices = data.get("choices", [])
            content = choices[0]["message"]["content"] if choices else ""
            usage = data.get("usage", {})

            return {
                "content": content,
                "model": data.get("model", model),
                "usage": {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                },
                "citations": data.get("citations", []),
            }

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Perplexity API error {e.response.status_code}: {e.response.text[:500]}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Perplexity request error: {e}")
            raise

    def research_company(
        self,
        company_name: str,
        website: str | None = None,
        industry: str | None = None,
        linkedin_url: str | None = None,
        location: str | None = None,
        additional_context: str = "",
    ) -> dict:
        """Research a manufacturing company for sales intelligence.

        This is the primary research call — one per company.

        Args:
            company_name: Company name.
            website: Company website URL.
            industry: Industry classification.
            linkedin_url: LinkedIn company URL.
            location: City, State, Country.
            additional_context: Any additional context to include.

        Returns:
            Dict with 'content' and 'usage'.
        """
        system_prompt = """You are a senior manufacturing industry analyst conducting deep research on
companies for strategic partnership evaluation. Your job is to thoroughly analyze manufacturing
companies and extract critical business intelligence relevant to an AI-powered manufacturing
intelligence platform.

Your research methodology:
1. Start with the company website — examine homepage, about page, products, capabilities, news/press releases
2. Search for recent news, press releases, and industry publications
3. Look for technology and operations information
4. Identify pain points, challenges, and opportunities

You must extract specific data points about:
- What they manufacture (products, processes, equipment)
- Technology systems in use (ERP, CMMS, SCADA, MES, PLCs)
- IoT and sensor infrastructure maturity
- Current maintenance approach (reactive, time-based, predictive)
- Recent news: expansions, M&A, leadership changes, downtime incidents
- Sustainability/ESG initiatives
- Digital transformation initiatives
- Any existing AI/ML or predictive analytics platforms
- Recent hiring in digital transformation / innovation roles
- Quality, workforce, or operational challenges mentioned

Provide honest, evidence-based analysis. If information is not available, clearly state this.
Do not fabricate data."""

        user_prompt = f"""Research this manufacturing company for sales intelligence:

COMPANY: {company_name}
WEBSITE: {website or 'Not available'}
INDUSTRY: {industry or 'Manufacturing'}
LINKEDIN: {linkedin_url or 'Not available'}
LOCATION: {location or 'Not available'}
{f'ADDITIONAL CONTEXT: {additional_context}' if additional_context else ''}

RESEARCH QUESTIONS:
1. What does this company manufacture? What are their main products and processes?
2. What technology systems do they use? (ERP: SAP/Oracle/Epicor/Infor? CMMS: Maximo/SAP PM/UpKeep? SCADA/MES: Rockwell/Siemens/Wonderware? PLCs: Allen-Bradley/Siemens?)
3. What is their IoT/sensor/Industry 4.0 maturity level?
4. What is their current maintenance approach? (reactive, time-based, condition-based, predictive?)
5. Any recent news? (plant expansions, acquisitions, leadership changes, equipment investments, downtime incidents)
6. Any sustainability/ESG initiatives?
7. Any digital transformation or Industry 4.0 initiatives announced?
8. Are they using any AI/ML platforms for manufacturing? (Uptake, SparkCognition, C3.ai, Sight Machine, MachineMetrics, etc.)
9. Have they recently hired digital transformation / innovation leadership roles?
10. What operational challenges or pain points are mentioned? (quality issues, workforce shortages, downtime, supply chain)

Provide your findings in a structured format with clear sections for each question.
If you cannot find information for a question, state "Not found" rather than speculating."""

        return self.chat_completion(system_prompt, user_prompt)

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
