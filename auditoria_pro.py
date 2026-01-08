import psycopg2
import pandas as pd
import os
from dotenv import load_dotenv

# Cargamos configuración
load_dotenv()
DIRECT_URL = os.getenv("DIRECT_URL")

def ejecutar_auditoria():
    print("🚀 Iniciando auditoría de integridad en Supabase...")
    try:
        conn = psycopg2.connect(DIRECT_URL)
        query = """
        SELECT 
            d.document_id, 
            d.source_filename, 
            COUNT(c.chunk_id) as total_chunks
        FROM documents d
        LEFT JOIN chunks c ON d.document_id = c.document_id
        GROUP BY d.document_id, d.source_filename
        ORDER BY total_chunks ASC;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()

        # Identificación de problemas
        df['estado'] = 'OK'
        df.loc[df['total_chunks'] == 0, 'estado'] = '🚨 VACÍO (Requiere recarga)'
        df.loc[(df['total_chunks'] > 0) & (df['total_chunks'] < 5), 'estado'] = '⚠️ SOSPECHOSO (Bajo)'

        # Generar CSV para el usuario
        df.to_csv('reporte_auditoria_fiscal.csv', index=False)
        
        # Resumen en consola
        vacios = df[df['total_chunks'] == 0]
        print(f"\n✅ Auditoría completa. Total documentos revisados: {len(df)}")
        print(f"❌ Documentos con 0 fragmentos: {len(vacios)}")
        if not vacios.empty:
            print("Lista de documentos para recargar:")
            for doc in vacios['document_id'].tolist():
                print(f"  - {doc}")
        
        print("\n💾 El detalle completo se guardó en: 'reporte_auditoria_fiscal.csv'")

    except Exception as e:
        print(f"❌ Error en la conexión: {e}")

if __name__ == "__main__":
    ejecutar_auditoria()