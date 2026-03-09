class ExternalTrackingService:
    @staticmethod
    def get_ocean_tracking(tracking_number, carrier_scac):
        # Stub: calls external Ocean API (e.g. Project44, MarineTraffic)
        return {
            'status': 'in_transit',
            'estimated_delivery': '2025-05-01',
            'latest_milestone': 'Vessel departed Origin Port',
            'coordinates': {'lat': 35.0, 'lng': -40.0}
        }

    @staticmethod
    def get_land_tracking(tracking_number, carrier_pronumber):
        # Stub: calls external Land API (e.g. FourKites, C.H. Robinson)
        return {
            'status': 'out_for_delivery',
            'estimated_delivery': '2025-04-10',
            'latest_milestone': 'Out for delivery to final destination',
            'coordinates': {'lat': 40.7128, 'lng': -74.0060}
        }

class FreightEstimationService:
    @staticmethod
    def estimate_freight_cost(origin, destination, weight, volume, is_ltl=True):
        # Stub: calls external pricing APIs (C.H. Robinson, FedEx Custom Critical)
        # Returns an estimated cost
        base_rate = 500
        distance_factor = 1.5  # placeholder logic
        weight_factor = weight * 0.1
        estimated_cost = base_rate + distance_factor * 100 + weight_factor
        return estimated_cost

class ProfitCalculator:
    @staticmethod
    def calculate_profit(sell_price, estimated_cost):
        profit = sell_price - estimated_cost
        margin = (profit / sell_price * 100) if sell_price > 0 else 0
        return {
            'profit': profit,
            'margin_percentage': round(margin, 2)
        }
