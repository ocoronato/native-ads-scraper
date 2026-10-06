# Segurança

## O que nunca entra no repositório

| Arquivo | Por quê |
| --- | --- |
| `r2.config.json` | credenciais do Cloudflare R2 em texto puro |
| `.env` | as mesmas credenciais, em outro formato |
| `data/` | a base coletada — dados seus, não código |
| `site/` | a cópia publicada da base |

Os quatro estão no `.gitignore`. Antes de um primeiro push, confira o que está
de fato na área de staging:

```bash
git add -A
git status --short
```

Se `r2.config.json`, `.env` ou qualquer coisa dentro de `data/` aparecer na
lista, **pare** e corrija o `.gitignore` antes de commitar.

## Se uma credencial vazar

Chave exposta é chave comprometida — não importa por quanto tempo ficou
visível, nem se o commit foi apagado depois, nem se a mensagem foi deletada.
O histórico do Git guarda, os espelhos copiam e os rastreadores indexam.

O procedimento é sempre o mesmo, nessa ordem:

1. **Revogue o token** no painel da Cloudflare: R2 → Manage API Tokens →
   o token → Revoke. Isso é o que efetivamente fecha a porta.
2. **Crie um novo** com permissão *Object Read & Write* restrita a um único
   bucket. Nunca um token de conta inteira.
3. **Reconfigure** com `python configurar_r2.py`.
4. Só então, se quiser, limpe o histórico. Essa etapa é cosmética: sem o
   passo 1 ela não protege nada.

## Escopo do token

O projeto só precisa de leitura e escrita de objeto em **um** bucket. Um token
com permissão de conta inteira transformaria um vazamento pequeno em acesso a
toda a sua Cloudflare.

## Reportar uma vulnerabilidade

Abra uma *issue* descrevendo o problema. Se for algo sensível que não deva
ficar público, marque a issue como tal ou use o canal privado de *security
advisory* do GitHub em vez da issue aberta.
