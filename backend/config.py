"""
Business configuration for the AI receptionist
Customize these values for your business
"""

BUSINESS_CONFIG = {
    "name": "Your Business Name",
    "hours": "Monday-Friday: 9 AM - 5 PM, Saturday: 10 AM - 2 PM",
    "phone": "(555) 123-4567",
    "email": "info@yourbusiness.com",
    "address": "123 Business Street, City, State 12345",
    "departments": [
        {
            "name": "Sales",
            "extension": "101",
            "description": "For sales inquiries and new customer onboarding"
        },
        {
            "name": "Support",
            "extension": "102",
            "description": "For technical support and customer service"
        },
        {
            "name": "Billing",
            "extension": "103",
            "description": "For billing questions and payment processing"
        },
        {
            "name": "General",
            "extension": "100",
            "description": "General inquiries"
        }
    ],
    "services": [
        "Consulting",
        "Product Sales",
        "Technical Support",
        "Custom Solutions"
    ],
    "greeting": "Thank you for calling {name}. This is your AI receptionist. How may I assist you today?",
    "closing": "Is there anything else I can help you with today?"
}





