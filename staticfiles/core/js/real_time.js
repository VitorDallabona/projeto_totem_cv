// SCRIPT PARA FAZER O REAL-TIME RENDERING DA TABELA

function fetchAttendances(){
    fetch('/dados-recentes/')
        .then(response=>response.json())
        .then(data=>{
            const tbody = document.querySelector('table tbody');
            tbody.innerHTML = ''; //limpa a tabela atual
            if(data.length===0){
                tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-3">Aguardando capturas...</td></tr>';
                return;
            }

            data.forEach(att=>{
                let badge = att.is_valid
                    ? '<span class="badge bg-success">Validado</span>'
                    : `<span class="badge bg-danger">Suspeito (${att.liveness_score})</span>`;
                
                let row = `<tr>
                    <td>${att.horario}</td>
                    <td>${att.aluno_nome}</td>
                    <td>${att.matricula}</td>
                    <td>${badge}</td>
                </tr>`;

                tbody.innerHTML += row;
            });
        })
        .catch(error=>console.error('Erro ao buscar presenças:', error));
}
fetchAttendances();
setInterval(fetchAttendances, 3000); //atualiza a cada 3s