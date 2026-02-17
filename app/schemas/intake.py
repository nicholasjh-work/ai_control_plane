from pydantic import BaseModel

class IntakeRequest(BaseModel):
    title: str
    description: str
    requester_email: str
    department: str
    system: str
    urgency: str

