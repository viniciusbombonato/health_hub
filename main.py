import phonenumbers
from fastapi import FastAPI, HTTPException

app = FastAPI()

@app.get("/")
def root():
    return "Health Hub"

@app.post("/health/{name}/{password}")
def health_hub(name: str, password: str):
    if name == "carol" and password == "viniciuslindo":
        return "Welcome Carol"
    else:
        raise HTTPException(status_code=404, detail="Qual a senha certa carolina?")



# Vou colocar aqui uma função para validar o número de telefone usando uma biblioteca do google
# decidi colocar aqui para verificar antes de mandar para o banco de dados

def valid_phone_number(phone: str, country_alpha2: str = "BR")-> str | None:
    try:
        validation = phonenumbers.parse(phone, country_alpha2)

        if phonenumbers.is_valid_number(validation):
            return phonenumbers.format_number(validation, phonenumbers.PhoneNumberFormat.E164)

        else:
            return None

    except phonenumbers.NumberParseException:
        return None

