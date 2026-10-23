{#
 # Copyright (C) 2026 yutong.li
 # All rights reserved.
 #
 # Redistribution and use in source and binary forms, with or without
 # modification, are permitted provided that the following conditions are met:
 #
 # 1. Redistributions of source code must retain the above copyright notice,
 #    this list of conditions and the following disclaimer.
 #
 # 2. Redistributions in binary form must reproduce the above copyright
 #    notice, this list of conditions and the following disclaimer in the
 #    documentation and/or other materials provided with the distribution.
 #
 # THIS SOFTWARE IS PROVIDED ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
 # INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
 # AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 # AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
 # OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 # SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 # INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 # CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 # ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 # POSSIBILITY OF SUCH DAMAGE.
 #}

<script>
    $(document).ready(function() {
        mapDataToFormUI({'frm_GeneralSettings': "/api/wan8021x/settings/get"}).done(function() {
            $('.selectpicker').selectpicker('refresh');
        });

        $("#{{formGridSupplicant['table_id']}}").UIBootgrid({
            search: '/api/wan8021x/settings/search_supplicant',
            get: '/api/wan8021x/settings/get_supplicant/',
            set: '/api/wan8021x/settings/set_supplicant/',
            add: '/api/wan8021x/settings/add_supplicant/',
            del: '/api/wan8021x/settings/del_supplicant/',
            toggle: '/api/wan8021x/settings/toggle_supplicant/'
        });

        $("#reconfigureAct").SimpleActionButton({
            onPreAction: function() {
                const dfObj = $.Deferred();
                saveFormToEndpoint("/api/wan8021x/settings/set", 'frm_GeneralSettings', dfObj.resolve, true, dfObj.reject);
                return dfObj;
            },
            onAction: function() {
                updateServiceControlUI('wan8021x');
                updateStatus();
            }
        });

        function stateLabel(row) {
            let cls = 'default';
            if (row.port == 'Authorized') {
                cls = 'success';
            } else if (row.state == 'failed') {
                cls = 'danger';
            } else if (row.state == 'authenticating' || row.state == 'starting') {
                cls = 'warning';
            }
            return $('<span class="label">').addClass('label-' + cls).text(row.port || row.state);
        }

        function updateStatus() {
            ajaxGet('/api/wan8021x/service/supplicants', {}, function(data) {
                const tbody = $('#supplicantStatus > tbody').empty();
                if (!data.rows || data.rows.length == 0) {
                    tbody.append($('<tr>').append($('<td colspan="7">').text("{{ lang._('No supplicant is running.') }}")));
                    return;
                }
                data.rows.forEach(function(row) {
                    const btn = $('<button class="btn btn-default btn-xs">')
                        .attr('title', "{{ lang._('Restart authentication') }}")
                        .append('<i class="fa fa-refresh fa-fw"></i>')
                        .click(function() {
                            ajaxCall('/api/wan8021x/service/reauthenticate/' + row.interface, {}, function() {
                                setTimeout(updateStatus, 2000);
                            });
                        });
                    tbody.append($('<tr>').append(
                        $('<td>').text(row.description || row.interface),
                        $('<td>').text(row.device),
                        $('<td>').append(stateLabel(row)),
                        $('<td>').text(row.eap_state || ''),
                        $('<td>').text(row.method || ''),
                        $('<td>').text(row.last_error || ''),
                        $('<td>').append(btn)
                    ));
                });
            });
        }

        $('a[href="#status"]').on('shown.bs.tab', updateStatus);
        setInterval(function() {
            if ($('#status').hasClass('active')) {
                updateStatus();
            }
        }, 5000);
        updateServiceControlUI('wan8021x');
    });
</script>

<ul class="nav nav-tabs" data-tabs="tabs" id="maintabs">
    <li class="active"><a data-toggle="tab" href="#supplicants">{{ lang._('Supplicants') }}</a></li>
    <li><a data-toggle="tab" href="#status">{{ lang._('Status') }}</a></li>
    <li><a data-toggle="tab" href="#general">{{ lang._('General') }}</a></li>
</ul>

<div class="tab-content content-box">
    <div id="supplicants" class="tab-pane fade in active">
        {{ partial('layout_partials/base_bootgrid_table', formGridSupplicant) }}
    </div>
    <div id="status" class="tab-pane fade in">
        <table id="supplicantStatus" class="table table-condensed table-striped">
            <thead>
                <tr>
                    <th>{{ lang._('Interface') }}</th>
                    <th>{{ lang._('Device') }}</th>
                    <th>{{ lang._('Port') }}</th>
                    <th>{{ lang._('EAP state') }}</th>
                    <th>{{ lang._('Method') }}</th>
                    <th>{{ lang._('Last error') }}</th>
                    <th></th>
                </tr>
            </thead>
            <tbody></tbody>
        </table>
    </div>
    <div id="general" class="tab-pane fade in">
        {{ partial('layout_partials/base_form', ['fields': generalForm, 'id': 'frm_GeneralSettings']) }}
    </div>
</div>

{{ partial('layout_partials/base_apply_button', {'data_endpoint': '/api/wan8021x/service/reconfigure', 'data_service_widget': 'wan8021x'}) }}
{{ partial('layout_partials/base_dialog', ['fields': formDialogSupplicant, 'id': formGridSupplicant['edit_dialog_id'], 'label': lang._('Edit supplicant')]) }}
