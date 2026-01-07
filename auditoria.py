from app.core.supabase_client import supabase

def realizar_auditoria():
    print("🔍 --- AUDITORÍA TÉCNICA: AGENTE FISCAL PRO ---")
    
    try:
        # 1. Obtener los documentos usando tus nombres de columna: document_id y title
        print("📡 Conectando con la tabla 'documents'...")
        res = supabase.table("documents").select("document_id, title").execute()
        documentos = res.data
        
        if not documentos:
            print("❌ No se encontraron registros en la tabla 'documents'.")
            return

        print(f"📊 Total de documentos en sistema: {len(documentos)}")
        print("-" * 70)
        print(f"{'N°':<4} | {'ID DEL DOCUMENTO':<20} | {'TÍTULO':<30} | {'CHUNKS'}")
        print("-" * 70)

        total_chunks_db = 0
        documentos_vacios = []

        for i, doc in enumerate(documentos, 1):
            doc_id = doc['document_id']
            titulo = doc['title'] if doc['title'] else "Sin título"
            
            # 2. Contar fragmentos en tu tabla 'chunks' usando 'document_id'
            res_chunks = supabase.table("chunks")\
                .select("chunk_id", count="exact")\
                .eq("document_id", doc_id)\
                .execute()
            
            conteo = res_chunks.count
            total_chunks_db += conteo

            # Mostrar resultado en tabla
            print(f"{i:<4} | {doc_id[:18]:<20} | {titulo[:28]:<30} | {conteo}")

            # Identificar sospechosos
            if conteo == 0:
                documentos_vacios.append(f"{doc_id} - {titulo}")

        print("-" * 70)
        print(f"✅ RESUMEN:")
        print(f"   - Total de fragmentos (chunks) analizados: {total_chunks_db}")
        
        if documentos_vacios:
            print(f"\n⚠️ ALERTA: Hay {len(documentos_vacios)} documentos con 0 fragmentos.")
            print("Necesitan ser procesados con el script de segmentación:")
            for d in documentos_vacios:
                print(f"   [!] {d}")
        else:
            print("\n✨ INTEGRIDAD TOTAL: Todos los documentos tienen fragmentos asignados.")

    except Exception as e:
        print(f"❌ Error durante el proceso: {e}")

if __name__ == "__main__":
    realizar_auditoria()