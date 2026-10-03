"""Execute the actual console detail render functions using Node and a small DOM target."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'), 'Node is needed for console render checks')
class ConsoleIntakeTests(unittest.TestCase):
    def test_details_keep_proposal_approval_unknowns_and_optional_learning_separate(self):
        template = (ROOT / 'ui/library.template.html').read_text()
        functions = template[template.index('      function scoreEntry('):template.index('      function currentStageLabel(')]
        harness = r'''
const assert = require('node:assert/strict');
const host = {innerHTML: ''};
const document = {getElementById: () => host};
const forgeConfig = {};
function escapeHtml(value) {return String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');}
'''
        cases = r'''
const base = {itemId:'PF-0001', assessed:false, assessmentStatus:'draft', scores:{},
 intake:{idea:'<script>untrusted</script>', support:'Unmeasured', unknowns:'No baseline', attribution:'unknown', confidence:'low', next_action:'Run a bounded comparison', citations:[], evidence_locations:[], conflicts:['Contradictory note']},
 recommendation:{disposition:'Test',rationale:'Try before adoption',applications:[{purpose:'Checklist',destination:'notes',project_path:'prompts/checklist.md',artifact_type:'technique',item_ids:['PF-0001','PF-0002'],evidence_limits:'No outcomes',success_check:'Compare errors'}]},
 optionalLearning:{status:'paused',mode:'standard',reason:'User paused exercise'},
 provenanceStatus:'verified', applicationState:'unassessed'};
renderAssessmentPanels(base);
assert(host.innerHTML.includes('Proposed use · not approval'));
assert(host.innerHTML.includes('External attribution: unknown. Local integrity: verified'));
assert(host.innerHTML.includes('PF-0001, PF-0002'));
assert(host.innerHTML.includes('Contradictory note'));
assert(host.innerHTML.includes('<details class="panel"><summary>Optional learning'));
assert(!host.innerHTML.includes('<script>untrusted'));
assert(host.innerHTML.includes('&lt;script&gt;untrusted'));
renderAssessmentPanels({...base,assessmentStatus:'failed',recommendation:null,intake:{...base.intake,failure:'Read interrupted'}});
assert(host.innerHTML.includes('Read interrupted'));
assert(host.innerHTML.includes('Run a bounded comparison'));
renderAssessmentPanels({...base,assessed:true,assessmentStatus:'assessed',dispositionEffective:'Test',applicationState:'exported',exports:[{id:'PFX-0001',target:'notes',approval:'approved',package:'ledger/exports/PFX-0001.md'}]});
assert(host.innerHTML.includes('approved'));
assert(host.innerHTML.includes('Outcome missing'));
renderAssessmentPanels({...base,assessmentStatus:null,intake:null});
assert(host.innerHTML.includes('Assessment pending'));
assert(host.innerHTML.includes('Optional learning'));
console.log('Console intake, failure, proposal, approval, missing-outcome, escaping, and learning rendering pass.');
'''
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'console.cjs'; script.write_text(harness+functions+cases)
            result=subprocess.run(['node',str(script)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
