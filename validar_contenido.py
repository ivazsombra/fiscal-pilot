from app.core.supabase_client import supabase

def validar_fragmento():
    # Vamos a probar con el primer documento de tu lista: Anexo20_RMF2022-DO
    doc_id_test = "RMF_2025-30122024" 
    
    print(f"🔍 Validando contenido del documento: {doc_id_test}")
    
    try:
        res = supabase.table("chunks")\
            .select("text")\
            .eq("document_id", doc_id_test)\
            .execute()
        
        if res.data:
            texto = res.data[0]['text']
            print("\n--- INICIO DEL TEXTO GUARDADO ---")
            print(texto[:1000]) # Mostramos solo los primeros 1000 caracteres
            print("\n--- FIN DEL EXTRACTO ---")
            print(f"\nLongitud total del fragmento: {len(texto)} caracteres.")
            
            if len(texto) < 2000:
                print("\n⚠️ RESULTADO: El fragmento es muy corto. Es casi seguro que el documento está incompleto.")
            else:
                print("\n✅ RESULTADO: El fragmento tiene contenido, pero si el PDF original tiene muchas páginas, sigue estando incompleto.")
        else:
            print("❌ No se encontró el fragmento.")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    validar_fragmento()