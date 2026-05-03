from pydantic import BaseModel
from typing import Optional

class LoginRequest(BaseModel):
    key: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class ResetPasswordRequest(BaseModel):
    new_password: str

class CreateUserRequest(BaseModel):
    key: str
    name: str
    initials: str
    role: str
    dept: str
    level: str = "dourado"
    color: str = "av-gold"
    access_level: int = 0
    is_admin: bool = False
    is_admin_user: bool = False
    is_rh: bool = False
    is_ouvidor: bool = False
    points: int = 100
    password: str
    hire_date: Optional[str] = None
    org_position: Optional[str] = 'colaborador'
    is_orcoma: Optional[bool] = False

class UpdateUserRequest(BaseModel):
    name: str
    initials: str
    role: str
    dept: str
    level: str
    color: str
    access_level: int
    is_admin: bool
    is_admin_user: bool
    is_rh: bool
    is_ouvidor: bool
    points: int
    hire_date: Optional[str] = None
    org_position: Optional[str] = 'colaborador'
    is_orcoma: Optional[bool] = False

class CreatePostRequest(BaseModel):
    feed: str = "feed"
    text: str
    image_url: Optional[str] = None
    embed_url: Optional[str] = None
    access_level: str = "all"
    comunicado_tipo: Optional[str] = None


class CommentRequest(BaseModel):
    text: str

class MuralItemRequest(BaseModel):
    tag: str
    title: str
    subtitle: str
    content: str
    image_url: Optional[str] = None

class FolderRequest(BaseModel):
    name: str
    icon: str = "📁"
    level: str = "all"
    drive_link: Optional[str] = None

class OuvidoriaRequest(BaseModel):
    category: str
    text: str
    author_display_name: Optional[str] = None

class OuvidoriaStatusRequest(BaseModel):
    status: str

class OuvidoriaResponseRequest(BaseModel):
    text: str

class ChatMessageRequest(BaseModel):
    room_id: str
    text: str

class SocialRoomRequest(BaseModel):
    name: str
    description: Optional[str] = ''
    is_private: Optional[bool] = False
    member_keys: Optional[list[str]] = []

class OrganogramRequest(BaseModel):
    user_key: str
    parent_key: Optional[str] = None
    position_order: int = 0
    org_tier: str = 'colaborador'

class MoodRequest(BaseModel):
    mood: str
    intensity: int
    reason: Optional[str] = None

class PointsRequest(BaseModel):
    points: int

class OrgEntry(BaseModel):
    user_key: str
    parent_key: str = ""
    position_order: int = 0
    org_tier: str = "colaborador"

class PriceDoctorRequest(BaseModel):
    folder_id: str
    name: str
    specialty: Optional[str] = ''
    crm: Optional[str] = ''
    rqe: Optional[str] = ''
    position_order: Optional[int] = 0

class PriceProcedureRequest(BaseModel):
    doctor_id: str
    name: str
    value_cash: Optional[float] = 0
    value_card_pix: Optional[float] = 0
    value_bradesco: Optional[float] = 0
    value_brv: Optional[float] = 0
    value_prefeitura: Optional[float] = 0
    position_order: Optional[int] = 0

class CalendarEventRequest(BaseModel):
    title: str
    description: Optional[str] = ''
    location: Optional[str] = ''
    color: Optional[str] = '#C9A84C'
    start_date: str
    end_date: str
    all_day: Optional[bool] = False
    is_public: Optional[bool] = False
    repeat_type: Optional[str] = 'none'

class FeedbackRequest(BaseModel):
    target_user_key: str
    evaluator_sector: str
    feedback_text: str
    rating: int
    action: str        # "add" ou "remove"
    points: int
