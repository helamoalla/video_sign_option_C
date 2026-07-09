from app.avatar.cwasa_arabic_provider import CwasaArabicProvider

provider = CwasaArabicProvider()

result = provider.generate(
    text="شكرا لحسن متابعتكم",
    language="arabic",
    output_path="outputs/cwasa_test.mp4"
)

print("Generated:", result)