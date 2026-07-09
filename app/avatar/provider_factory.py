from app.avatar.placeholder_provider import PlaceholderAvatarProvider
from app.avatar.cwasa_arabic_provider import CwasaArabicProvider
from app.avatar.cwasa_multilang_provider import CwasaMultilangProvider

def get_avatar_provider(provider_name: str = 'placeholder'):
    provider_name=provider_name.lower().strip()
    if provider_name=='placeholder': return PlaceholderAvatarProvider()
    if provider_name in {'cwasa_arabic','cwasa'}: return CwasaArabicProvider()
    if provider_name in {'cwasa_multilang','cwasa_multilingual'}: return CwasaMultilangProvider()
    raise ValueError(f'Unknown avatar provider: {provider_name}')


