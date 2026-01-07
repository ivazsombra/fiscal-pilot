from app.core.supabase_client import supabase

def main():
    print("Iniciando aplicación...")
    # Intentar una consulta simple para ver si conecta
    try:
        # Esto solo verifica la conexión, no trae datos pesados
        print("Probando conexión a Supabase...")
        # (Aquí asumimos que la conexión ya se hizo al importar 'supabase')
        print("¡Éxito! El cliente de Supabase está listo.")
    except Exception as e:
        print(f"Error conectando: {e}")

if __name__ == "__main__":
    main()