"""
Smart Matching Engine — matches buyer requirements against available inventory.
Uses keyword/fuzzy string matching (upgradeable to embeddings when API key is available).
"""
import re
import logging
from difflib import SequenceMatcher

from django.db.models import Q

logger = logging.getLogger('apps.ai_assistant')


def stem(word):
    """Simple stemming to handle plurals like 'scraps' -> 'scrap'"""
    w = word.lower()
    if len(w) > 4:
        if w.endswith('ies'): return w[:-3] + 'y'
        if w.endswith('es'): return w[:-2]
        if w.endswith('s') and not w.endswith('ss'): return w[:-1]
    return w


# Semantic Dictionary — mapping all variations to a single canonical term
MATERIAL_SYNONYMS = {
    'alu': 'aluminum',
    'aluminium': 'aluminum',
    'cu': 'copper',
    'fe': 'iron',
    'scrap': 'scrap',
    'waste': 'scrap',
    'trash': 'scrap',
    'regrind': 'regrind',
    'granules': 'regrind',
    'hdpe': 'hdpe',
    'polyethylene': 'hdpe',
    'ldpe': 'ldpe',
    'pp': 'pp',
    'polypropylene': 'pp',
    'pet': 'pet',
    'pvc': 'pvc',
    'si': 'silicon',
    'abs': 'abs',
    'pcb': 'electronics',
    'computer': 'electronics',
    'laptop': 'electronics',
    'cardboard': 'paper',
    'carton': 'paper',
    'metal': 'raw_materials',
    'alloy': 'raw_materials',
}

# High-priority keywords that should carry more weight in matching
MATCH_WEIGHTS = {
    'aluminum': 2.0,
    'copper': 2.0,
    'iron': 2.0,
    'steel': 2.0,
    'hdpe': 2.0,
    'ldpe': 2.0,
    'pp': 2.0,
    'pvc': 2.0,
    'electronics': 1.8,
    'scrap': 1.2,
    'regrind': 1.5,
}


def normalize_material_text(text):
    """Normalize text and replace common synonyms for better matching"""
    if not text: return ""
    tokens = [stem(w) for w in re.findall(r'\w+', text.lower())]
    normalized = []
    for t in tokens:
        normalized.append(MATERIAL_SYNONYMS.get(t, t))
    return " ".join(normalized)


def compute_semantic_similarity(text1, text2):
    """
    Compute semantic similarity using weighted keyword overlap.
    Mimics Vector Cosine Similarity without heavy dependencies.
    """
    if not text1 or not text2: return 0
    
    # 1. Normalize both texts (Stemming + Synonyms)
    t1 = normalize_material_text(text1)
    t2 = normalize_material_text(text2)
    
    # 2. Exact or Substring match after normalization (High Confidence)
    if t1 == t2: return 100
    if t1 in t2 or t2 in t1: return 90
    
    # 3. Tokenize
    set1 = set(t1.split())
    set2 = set(t2.split())
    
    if not set1 or not set2: return 0
    intersection = set1.intersection(set2)
    
    # 4. Calculate weighted overlap ratio
    total_weight = sum(MATCH_WEIGHTS.get(w, 1.0) for w in (set1 | set2))
    match_weight = sum(MATCH_WEIGHTS.get(w, 1.0) for w in intersection)
    
    score = int((match_weight / total_weight) * 100) if total_weight > 0 else 0
    
    # 5. Fallback to sequence similarity for fuzzy spelling
    fuzzy_score = int(SequenceMatcher(None, t1, t2).ratio() * 100)
    
    return max(score, fuzzy_score)


def get_ai_match_insight(requirement, item):
    """
    Uses LLM to explain why two items match, especially for fuzzy matches.
    """
    from django.conf import settings
    import anthropic
    
    api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
    if not api_key:
        return "Matched based on material category and keyword similarity."

    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""
        Analyze if this Buyer Requirement matches this Inventory Item. 
        Buyer wants: {requirement.material_name} ({requirement.material_type})
        Inventory has: {item.product_name} ({item.description})
        
        Explain in 1 short sentence why this is a good match for a scrap metal/recycling broker.
        """
        response = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Error getting Claude match insight: {e}")
        return "Semantic overlap detected in material grades."


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
        name_sim = compute_semantic_similarity(search_term, item.product_name)
        if name_sim >= 30:
            score += name_sim * 0.6  # 60% weight on name
            reasons.append(f"Name match: {name_sim}%")

        # Material type similarity
        if material_type and hasattr(item, 'description'):
            type_sim = compute_semantic_similarity(material_type, item.description or '')
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
                insight = get_ai_match_insight(req, item) if score >= 70 else reason
                
                SmartMatch.objects.create(
                    tenant=tenant,
                    requirement=req,
                    inventory_item=item,
                    confidence_score=score,
                    match_reason=insight,
                )
                total_matches += 1

    logger.info(f"Created {total_matches} new matches")
    return total_matches
