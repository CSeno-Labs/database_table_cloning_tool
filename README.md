# sync-db 🚀

Uma ferramenta CLI em Python projetada para sincronizar tabelas específicas entre ambientes MySQL (ex: Produção para Localhost) de forma inteligente, segura e visual.

## ✨ Funcionalidades

* **Sincronização Inteligente**: Detecta se a tabela existe no destino. Se não existir, cria a estrutura; se existir, verifica se há colunas novas na origem e as adiciona automaticamente.
* **Interface Moderna**: Utiliza a biblioteca `rich` para exibir painéis, cores e barras de progresso reais durante a importação.
* **Eficiência**: Processa arquivos grandes via streaming (chunks), economizando memória RAM.
* **Logs Detalhados**: Histórico completo de operações salvo em arquivo.
* **Configuração Centralizada**: Credenciais e preferências separadas em um arquivo `config.json`.

## 🛠️ Pré-requisitos

1. **Python 3.10+** instalado.
2. **MySQL Client** (mysqldump e mysql) instalado (geralmente via XAMPP ou instalação nativa).
3. Dependências Python:

```bash
   pip install mysql-connector-python rich
   ```

## ⚙️ Configuração

Edite o arquivo `config.json` na pasta raiz do projeto:

```json
{
    "settings": {
        "mysql\_bin\_path": "C:\\\\xampp\\\\mysql\\\\bin",
        "default\_csv\_file": "tabelas\_puxar.csv",
        "log\_file": "sincronizacao.log"
    },
    "origem": {
        "alias": "PRODUÇÃO (RDS)",
        "host": "seu-host.rds.amazonaws.com",
        "user": "usuario",
        "password": "senha",
        "database": "nome\_db"

&nbsp;	"charset": ""
    },
    "destino": {
        "alias": "LOCAL (DEV)",
        "host": "localhost",
        "user": "root",
        "password": "1",
        "database": "nome\_db"

&nbsp;	"charset": ""
    }
}
```

## 🚀 Como usar

### Uso Básico

Sincroniza as tabelas listadas no arquivo padrão (`tabelas\_puxar.csv`):

```bash
python sync-db.py
```

### Argumentos de Linha de Comando

Você pode passar tabelas específicas ou arquivos personalizados:

* **Tabelas manuais**: `python sync-db.py -t aluno escola lotacao`
* **Arquivo personalizado**: `python sync-db.py -f tabelas\_especificas.txt`
* **Apenas visualizar (Dry Run)**: `python sync-db.py -s` (Mostra quais tabelas seriam afetadas)
* **Ver Logs**: `python sync-db.py -l` (Mostra as últimas 20 entradas do log)

---

## 💻 Configurando o Comando Global (Windows)

Para rodar o `sync-db` de qualquer pasta no seu computador:

1. Na pasta do projeto, você encontrará o arquivo `sinc-db.bat`.
2. Abra o menu Iniciar e digite **"Variáveis de ambiente"**.
3. Selecione **"Editar as variáveis de ambiente do sistema"**.
4. Clique em **Variáveis de Ambiente** > **Variáveis do Sistema** > selecione **Path** e clique em **Editar**.
5. Clique em **Novo** e cole o caminho completo da pasta onde está o arquivo `sinc-db.bat`.
6. Reinicie seu terminal.

Agora você pode usar o comando abaixo de qualquer diretório:

```bash
sinc-db -t minha\_tabela
```

---

*Desenvolvido por S\_Neto99*

