"""
Smart Matching Engine — matches buyer requirements against available inventory.
Uses keyword/fuzzy string matching (upgradeable to embeddings when API key is available).
"""
import re
import logging
from difflib import SequenceMatcher

from django.db.models import Q

logger = logging.getLogger('apps.ai_assistant')


def compute_similarity(text1, text2):
    """Compute similarity between two strings (0-100)"""
    if not text1 or not text2:
        return 0
    t1 = text1.lower().strip()
    t2 = text2.lower().strip()
    # Exact match
    if t1 == t2:
        return 100
    # Contains match
    if t1 in t2 or t2 in t1:
        return 85
    # Sequence similarity
    return int(SequenceMatcher(None, t1, t2).ratio() * 100)


def match_requirement_to_inventory(requirement, tenant):
    """
    Find matching inventory items for a buyer requirement.
    Returns list of (inventory_item, confidence_score, reason).
    """
    from apps.inventory.models import InventoryItem

    results = []
    search_term = requirement.material_name.lower()
    material_type = requirement.material_type.lower() if requirement.material_type else ''

    # Step 1: Direct name match
    items = InventoryItem.objects.filter(
        tenant=tenant,
        quantity__gt=0,
    )

    for item in items:
        score = 0
        reasons = []

        # Name similarity
        name_sim = compute_similarity(search_term, item.product_name)
        if name_sim >= 30:
            score += name_sim * 0.6  # 60% weight on name
            reasons.append(f"Name match: {name_sim}%")

        # Material type similarity
        if material_type and hasattr(item, 'description'):
            type_sim = compute_similarity(material_type, item.description or '')
            if type_sim >= 20:
                score += type_sim * 0.2
                reasons.append(f"Description match: {type_sim}%")

        # Quantity availability check
        if requirement.quantity_needed and item.quantity:
            if item.quantity >= requirement.quantity_needed:
                score += 10
                reasons.append("Sufficient quantity available")
            else:
                score += 5
                reasons.append(f"Partial quantity: {item.quantity}/{requirement.quantity_needed}")

        # Price check
        if requirement.max_price and item.unit_cost:
            if item.unit_cost <= requirement.max_price:
                score += 10
                reasons.append("Within price range")
            else:
                score -= 5
                reasons.append(f"Above max price (${item.unit_cost} > ${requirement.max_price})")

        if score >= 20:
            results.append((item, min(score, 100), " | ".join(reasons)))

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:10]  # Top 10 matches


def run_matching(tenant):
    """
    Run matching for all unfulfilled buyer requirements.
    Creates SmartMatch records for new matches.
    """
    from .models import BuyerRequirement, SmartMatch

    requirements = BuyerRequirement.objects.filter(
        tenant=tenant,
        is_fulfilled=False,
    )

    total_matches = 0
    for req in requirements:
        matches = match_requirement_to_inventory(req, tenant)
        for item, score, reason in matches:
            # Don't create duplicate matches
            if not SmartMatch.objects.filter(
                tenant=tenant,
                requirement=req,
                inventory_item=item,
            ).exists():
                SmartMatch.objects.create(
                    tenant=tenant,
                    requirement=req,
                    inventory_item=item,
                    confidence_score=score,
                    match_reason=reason,
                )
                total_matches += 1

    logger.info(f"Created {total_matches} new matches")
    return total_matches
