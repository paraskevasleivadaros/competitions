# This file contains all functions available to compute numerical results
# for user uploaded method results.
# Except: evaluator_worker . This is used as the thread that wraps calls
# to evaluator_function in views.py .

from django.conf import settings
from django.core.mail import send_mail, EmailMessage
from random import random
from time import sleep
from os import listdir, makedirs, remove, path, walk
from os.path import splitext, isdir, isfile, join, abspath, normpath, basename
from shutil import copyfile, rmtree
from subprocess import PIPE, Popen
from uuid import uuid4
from json import dumps
import re
import sys
import tarfile

# from importlib.machinery import SourceFileLoader


temporary_folder = '/tmp/'


def cmdline(command, *args, **kwargs):
    # http://stackoverflow.com/questions/3503879/assign-output-of-os-system-to-a-variable-and-prevent-it-from-being-displayed-on
    # http://stackoverflow.com/questions/17615414/how-to-convert-binary-string-to-normal-string-in-python3
    # http://stackoverflow.com/questions/13744473/command-line-execution-in-different-folder
    cwd = kwargs.pop('cwd', None)
    process = Popen(
        args=command,
        stdout=PIPE,
        shell=True,
        cwd=cwd,
    )
    res = process.communicate()[0]
    return res.decode('utf-8')


def send_feedback(submission_status, logfile, individu):
    uname = individu.user.username
    status = submission_status.status
    competition = submission_status.submission.subtrack.track.competition
    cc_email = competition.cc_email
    # TODO: Maybe all cosubmitters should be notified
    # TODO: Maybe add more info about the submission
    uemail = individu.user.email
    if status == "COMPLETE":
        status_final = 'Evaluation finished succesfully.'
    elif status == "ERROR_EVALUATOR":
        status_final = 'Evaluation internal error; evaluator not found.'
    elif status == "ERROR_UNSUPPORTED":
        status_final = 'Evaluation internal error; benchmark unsupported.'
    elif status == "ERROR_PROCESSING":
        status_final = 'Evaluation error; an error occured while processing your file.'
    else:
        status_final = 'Unknown error.'
    cclist = [settings.EMAIL_ADMINISTRATOR]
    if cc_email != '':
        cclist.append(cc_email)
    email = EmailMessage(
        'Submission to Scriptnet',
        """
This email is sent as feedback because you have submitted a result file to the ScriptNet Competitions Site.
Competition: {}
Username: {}
{} (return code: {})

Evaluator log (if any:)
{}

ScriptNet is hosted by the National Centre of Scientific Research Demokritos and co-financed by the H2020 Project READ (Recognition and Enrichment of Archival Documents):
http://read.transkribus.eu/
        """.format(competition.name , uname, status_final, status, logfile),
        settings.EMAIL_HOST_USER,
        [uemail],
        cclist,
    )
    email.send(fail_silently=False)


def evaluator_worker(evaluator_function, submission_status_set, individu):
    logfile = ''
    if not evaluator_function:
        for s in submission_status_set:
            s.status = "ERROR_EVALUATOR"
            s.save()
        send_feedback(s, logfile, individu)
        return
    else:
        try:
            for s in submission_status_set:
                # ugly; works because submission should be the same for all
                submission = s.submission
                s.status = "PROCESSING"
                s.save()
            res = evaluator_function(
                privatedata=submission.subtrack.private_data_unpacked_folder(),
                resultdata=submission.resultfile.name,
            )
            if (isinstance(res, dict)):
                result_dictionary = res
            else:
                (result_dictionary, logfile) = res
            for s in submission_status_set:
                benchname = s.benchmark.name
                if benchname in result_dictionary.keys():
                    s.status = "COMPLETE"
                    s.numericalresult = result_dictionary[benchname]
                    s.save()
                else:
                    s.status = "ERROR_UNSUPPORTED"
                    s.numericalresult = ''
                    s.save()
            send_feedback(s, logfile, individu)
        except:
            for s in submission_status_set:
                s.status = "ERROR_PROCESSING"
                s.save()
            logfile = logfile + str(sys.exc_info())
            send_feedback(s, logfile, individu)
            return


def random_numbers(*args, **kwargs):
    sleep(20)
    result = {
        'random_integer': int(random() * 10000),
        'random_percentage': random()
    }
    return result


def icfhr14_kws_tool(*args, **kwargs):
    executable_folder = \
        '{}/competitions/executables/VCGEvalConsole.linux' \
            .format(settings.BASE_DIR)
    resultdata = kwargs.pop('resultdata',
                            '{}/WordSpottingResultsSample.xml'
                            .format(executable_folder))
    privatedata = kwargs.pop('privatedata',
                             '{}/GroundTruthRelevanceJudgementsSample.xml'.
                             format(executable_folder))
    n_xml = 0
    if isdir(privatedata):
        for fn in listdir(privatedata):
            fn_base, fn_ext = splitext(fn)
            if (fn_ext.lower() == '.xml'):
                n_xml = n_xml + 1
                privatedata = '{}{}'.format(privatedata, fn)
    else:
        n_xml = 1

    if (n_xml != 1):
        raise IOError('The private data folder does not contain exactly ' +
                      'one ground-truth file')

    executable = '{}/VCGEvalConsole.sh'.format(executable_folder)
    commandline = '{} {} {}'.format(executable, privatedata, resultdata)
    command_output = cmdline(commandline)

    rgx = r'ALL QUERIES\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)' \
          '\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)' \
          '\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)' \
          '\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)'
    r = re.search(rgx, command_output)
    result = {
        'p@5': r.group(1),
        'p@10': r.group(2),
        'r-precision': r.group(3),
        'map': r.group(4),
        'ndcg-binary': r.group(5),
        'ndcg': r.group(6),
        'pr-curve': dumps([r.group(7), r.group(8), r.group(9),
                           r.group(10), r.group(11), r.group(12),
                           r.group(13), r.group(14), r.group(15),
                           r.group(16), r.group(17)])
    }
    return (result, command_output)


def transkribusBaseLineMetricTool(*args, **kwargs):
    executable_folder = \
        '{}/competitions/executables/TranskribusBaseLineMetricTool' \
            .format(settings.BASE_DIR)
    # resultdata = kwargs.pop('resultdata', 'reco.lst')
    resultdata = kwargs.pop('resultdata', executable_folder + '/HYPO.tar')
    # privatedata = kwargs.pop('privatedata', 'truth.lst')
    privatedata = kwargs.pop('privatedata', executable_folder + '/GT')

    executable_jar = 'baselineTool.jar'
    if (isdir(privatedata)):
        print(resultdata)
        print(privatedata)
        # This is the non-test scenario
        # Hence we have to create a temporary folder and copy everything there
        newfolder = '{}{}/'.format(temporary_folder, uuid4().hex)
        makedirs(newfolder)
        # Since truth and hypo could be named equally we have to create two folders
        hypofolder = join(newfolder, 'hypo')
        makedirs(hypofolder)
        truthfolder = join(newfolder, 'truth')
        makedirs(truthfolder)
        if (isdir(resultdata)):
            cmdline('cp -r ' + resultdata + ' ' + hypofolder, cwd=newfolder)
        else:
            # If it is a file, it must be a tarball, or else raise an error
            tar = tarfile.open(resultdata)
            tar.extractall(hypofolder)
            tar.close()
        cmdline('cp -r ' + privatedata + ' ' + truthfolder)
        # Resultdata contains the folder structure of the result files

        cmdline('find ' + hypofolder + ' -name "*.txt" > tmp.lst', cwd=newfolder)
        cmdline('find ' + hypofolder + ' -name "*.xml" >> tmp.lst', cwd=newfolder)
        cmdline('cat tmp.lst | sort > reco.lst', cwd=newfolder)
        cmdline('rm tmp.lst', cwd=newfolder)
        cmdline('find ' + truthfolder + ' -name "*.txt" > tmp.lst', cwd=newfolder)
        cmdline('find ' + truthfolder + ' -name "*.xml" >> tmp.lst', cwd=newfolder)
        cmdline('cat tmp.lst | sort > truth.lst', cwd=newfolder)
        cmdline('rm tmp.lst', cwd=newfolder)

        copyfile(join(executable_folder, executable_jar), join(newfolder,
                                                               executable_jar))
        executable_folder = newfolder
        resultdata = '{}reco.lst'.format(newfolder)
        privatedata = '{}truth.lst'.format(newfolder)

    executable = 'java -jar {}'.format(executable_jar)
    commandline = '{} {} {}'.format(executable, privatedata, resultdata)
    command_output = cmdline(commandline, cwd=executable_folder)

    rmtree(newfolder)
    print(command_output)
    rgx = r'Avg \(over pages\) P value: ([\d\.]+)\nAvg \(over pages\) ' \
          'R value: ([\d\.]+)\nResulting F_1 value: ([\d\.]+)'
    r = re.search(rgx, command_output)
    result = {
        'bl-avg-P-value': r.group(1),
        'bl-avg-R-value': r.group(2),
        'bl-F_1-value': r.group(3),
    }
    return (result, command_output)


def transkribusErrorRate(*args, **kwargs):
    # the method assumes the following parameters:
    # kwargs has to contain "privatedata" with the path to a tar-file.
    # The tar-file has to contain Page-xml-files without subfolders.
    # The TextEquiv of the lines have to be the ground truth for the
    # competition.
    # kwargs also has to contain "resultdata",
    # which is the path to the tar-file containing the hypothesises of the
    # competitor.
    # kwargs can contain a path "tmpfolder" - all temporary files and folder
    # are created there.
    # the folder will be deleted afterwards, when it did not exist before.
    # Otherwise only the containing files and folders are deleted.

    folder_data = kwargs.pop('tmpfolder', normpath(abspath(".")))
    folder_exec = kwargs.pop("execpath",
                             join(normpath(abspath(".")),
                                  "executables/TranskribusErrorRate"))
    privatedata = kwargs.pop('privatedata', "gt.tgz")
    resultdata = kwargs.pop('resultdata', "hyp.tgz")
    print("privatedata is '" + privatedata + "'.")
    print("resultdata is '" + resultdata + "'.")
    print("folder_exec is '" + folder_exec + "'.")
    params = kwargs.pop("params", "")
    file_exec = join(folder_exec, 'TranskribusErrorRate.jar')

    data_lists = {}
    to_remove_folder = []
    to_remove_file = []
    deleteroot = False
    if not (isdir(folder_data)):
        print("folder have to be deleted")
        deleteroot = True
    for (file_tar, prefix) in [[privatedata, "gt"], [resultdata, "hyp"]]:
        print("execute '" + file_tar + "' ...")
        folder_xmls = join(folder_data, prefix + '_dir')
        print(folder_xmls)
        if isdir(folder_xmls):
            rmtree(folder_xmls)
        makedirs(folder_xmls)  # , exist_ok=True)
        to_remove_folder += [folder_xmls]
        print("unpack tar-file ...")
        obj_tar = tarfile.open(file_tar)
        obj_tar.extractall(folder_xmls)
        obj_tar.close()
        print("unpack tar-file ... [DONE]")
        print("save list ...")
        files_xml = sorted(listdir(folder_xmls))
        file_list_xml = join(folder_data, prefix + '.lst')
        to_remove_file += [file_list_xml]
        data_lists[file_tar] = file_list_xml
        with open(file_list_xml, 'w') as tfFile:
            for file_xml in files_xml:
                tfFile.write(join(folder_xmls, file_xml) + "\n")
                #                print(join(folder_xmls, file_xml), file=tfFile)
        print("save list ... [DONE] (to '" + file_list_xml + "')")
    if (deleteroot):
        to_remove_folder += [folder_data]

    executable = 'java -cp {} eu.transkribus.errorrate.ErrorRateParser'.format(
        file_exec)
    commandline = '{} {} {} {}'.format(
        executable, params, data_lists[privatedata], data_lists[resultdata])
    print(commandline)
    #    command_output = "tryrun"
    command_output = cmdline(commandline)
    print("output of algorithm:")
    print(command_output)
    print("output of algorithm: [DONE]")
    for file in to_remove_file:
        print("remove '" + file + "'")
        remove(file)
    for folder in to_remove_folder:
        print("remove '" + folder + "'")
        rmtree(folder)
    rgx = r'.*SUB = ([\d\.]+).*\nDEL = ([\d\.]+).*\nINS ' \
          '= ([\d\.]+).*\nERR = ([\d\.]+).*'
    r = re.search(rgx, command_output)
    result = {
        'ERR': r.group(4).encode("utf-8"),
        'INS': r.group(3).encode("utf-8"),
        'DEL': r.group(2).encode("utf-8"),
        'SUB': r.group(1).encode("utf-8"),
    }
    return result


def icfhr18_atr_tool(*args, **kwargs):
    # the method assumes the following parameters:
    # kwargs has to contain "privatedata" with the path to a tar-file.
    # The tar-file has to contain txt-files without subfolders.
    # Each txt file contains the line id and the corresponding ground truth.
    # kwargs also has to contain "resultdata",
    # which is the path to the tar-file containing the hypothesises of the
    # competitor of the same
    # the folder will be deleted afterwards, when it did not exist before.
    # Otherwise only the containing files and folders are deleted.
    def calc_error_rates(folder_exec, privatedata, resultdata):
        print("privatedata is '" + privatedata + "'.")
        print("resultdata is '" + resultdata + "'.")
        print("folder_exec is '" + folder_exec + "'.")

        folder_data = join(folder_exec, "tmp/")
        file_exec = join(folder_exec, 'TranskribusErrorRate-2.2.3-with-dependencies.jar')

        to_remove_folder = []
        to_remove_file = []
        delete_root = False
        if not (isdir(folder_data)):
            print("folder have to be deleted")
            delete_root = True
            makedirs(folder_data)

        gt_dict = fill_dict(privatedata)
    
        command_output = ""    
        
        folder_txt = join(folder_data, 'hyp_dir')
        unpacktar(resultdata,folder_txt)
        to_remove_folder.append(folder_txt)
        l = [join(folder_txt, fname) for fname in listdir(folder_txt)]
        to_remove_file.extend(l)
        hyp_dict = fill_dict(folder_txt)

        doc_ids = []
        pages = []

        # parse dicts
        for file_id in gt_dict:
            split = file_id.replace('.', '_').split("_")
            num_of_pages = split[1]
            doc_id = split[0]
            if doc_id not in doc_ids:
                doc_ids.append(doc_id)
            if num_of_pages not in pages:
                pages.append(num_of_pages)

            gt_file_name_did = join(folder_data, "tmp_gt_doc_" + doc_id + ".txt")
            hyp_file_name_did = join(folder_data, "tmp_hyp_doc_" + doc_id + ".txt")
            gt_file_name_pages = join(folder_data, "tmp_gt_" + num_of_pages + ".txt")
            hyp_file_name_pages = join(folder_data, "tmp_hyp_" + num_of_pages + ".txt")
            gt_file_name_total = join(folder_data, "tmp_gt.txt")
            hyp_file_name_total = join(folder_data, "tmp_hyp.txt")

            for file in [gt_file_name_did, gt_file_name_pages, gt_file_name_total, hyp_file_name_did, hyp_file_name_pages,
                        hyp_file_name_total]:
                if file not in to_remove_file:
                    to_remove_file.append(file)

            cur_gt_dict = gt_dict[file_id]
            cur_hyp_dict = hyp_dict[file_id]

            try:
                with open(gt_file_name_did, 'a', encoding='utf-8') as gtDocFile, open(hyp_file_name_did, 'a', encoding='utf-8') as hypDocFile, open(
                        gt_file_name_pages, 'a', encoding='utf-8') as gtPagesFile, \
                        open(hyp_file_name_pages, 'a', encoding='utf-8') as hypPagesFile, open(gt_file_name_total, 'a', encoding='utf-8') as gtFile, open(
                    hyp_file_name_total, 'a', encoding='utf-8') as hypFile:
                    for key in cur_gt_dict.keys():
                        text_gt = cur_gt_dict[key]
                        text_hyp = ""
                        if key not in cur_hyp_dict:
                            cur_hyp_dict.update({key: ""})
                            text_hyp = "\n"
                        else:
                            text_hyp = cur_hyp_dict[key]

                        gtDocFile.write(text_gt)
                        hypDocFile.write(text_hyp)
                        gtPagesFile.write(text_gt)
                        hypPagesFile.write(text_hyp)
                        gtFile.write(text_gt)
                        hypFile.write(text_hyp)
            except:
                command_output += str(sys.exc_info())
                return _, command_output
            if len(cur_gt_dict) != len(cur_hyp_dict):
                message = "WARNING: Some line ids in hypotheses of file {} are not in ground truth.\n".format(file_id)
                print(message)
                command_output += message

        command_output += "\nResults per additional specific training pages:\n"
        for page in sorted([int(x) for x in pages]):
            gt_file_name = join(folder_data, "tmp_gt_" + str(page) + ".txt")
            hyp_file_name = join(folder_data, "tmp_hyp_" + str(page) + ".txt")
            r, command_output = get_result(file_exec, gt_file_name, hyp_file_name, command_output, True)
            command_output += "{:<11d}: {:.6f} \n".format(page, float(r.group(1)))
        
        command_output += "\nResults per test collection:\n"
        for doc_id in sorted(doc_ids):
            gt_file_name = join(folder_data, "tmp_gt_doc_" + doc_id + ".txt")
            hyp_file_name = join(folder_data, "tmp_hyp_doc_" + doc_id + ".txt")
            r, command_output = get_result(file_exec, gt_file_name, hyp_file_name, command_output, True)
            command_output += "{:11s}: {:.6f} \n".format(doc_id, float(r.group(1)))

        gt_file_name = join(folder_data, "tmp_gt.txt")
        hyp_file_name = join(folder_data, "tmp_hyp.txt")
        r, command_output = get_result(file_exec, gt_file_name, hyp_file_name, command_output, True)
        command_output += "\n{:11s}: {:.6f} \n".format("total error", float(r.group(1)))

        print("output of algorithm:")
        print(command_output)
        print("output of algorithm: [DONE]")

        # tidy up everything

        print(to_remove_folder)

        if delete_root:
            to_remove_folder += [folder_data]
        for file in to_remove_file:
            print("remove '" + file + "'")
            remove(file)
        for folder in to_remove_folder:
            print("remove '" + folder + "'")
            rmtree(folder)

        result = {
            'CER': float(r.group(1)),
            'INS': float(r.group(3)),
            'DEL': float(r.group(2)),
            'SUB': float(r.group(4)),
        }
        return result, command_output


    def get_result(file_exec, gt_file_name, hyp_file_name, command_output, addToOutput):
        executable = 'java -cp {} eu.transkribus.errorrate.HtrErrorTxt -n -d'.format(
            file_exec)
        commandline = '{} {} {}'.format(executable, gt_file_name, hyp_file_name)

        # print(commandline)
        tmp_output = cmdline(commandline)
        if addToOutput:
            command_output = "Detailed confusion map: \n{}\n{}".format(tmp_output, command_output)

        rgx = r'.*ERR=([\d\.E+-]+).*\nDEL=([\d\.E+-]+).*\nINS=([\d\.E+-]+).*\nSUB=([\d\.E+-]+).*\n.*'
        r = re.search(rgx, tmp_output)

        return r, command_output


    def fill_dict(folder_data):
        # helper function
        print("processing '" + folder_data + "' ...")
        folder_txt = folder_data
        print("fill dict ...")
        files_txt = sorted(listdir(folder_txt))
        dictionary = {}
        for file_txt in files_txt:
            texts = []
            line_ids = []
            with open(join(folder_txt, file_txt), 'r+', encoding='utf-8') as tfFile:
                for line in tfFile:
                    split = line.split(" ", 1)
                    line_id = split[0]
                    text = split[1]
                    line_ids.append(line_id)
                    texts.append(text)
            d = dict(zip(line_ids, texts))
            dictionary[basename(file_txt)] = d
        print("fill dict done")
        return dictionary


    def unpacktar(file_tar,dest_dir):
        print("preparing result dir")
        if isdir(dest_dir):
            rmtree(dest_dir)
        makedirs(dest_dir)

        print("unpack tar-file ..." + file_tar)
        try:
            obj_tar = tarfile.open(file_tar)
            obj_tar.extractall(dest_dir)
            obj_tar.close()
        except:
            print(sys.exc_info()[0])
            raise
        print("unpack tar-file done")


    folder_exec = kwargs.pop("execpath",'{}/competitions/executables/TranskribusErrorRate'.format(settings.BASE_DIR))
    privatedata = kwargs.pop('privatedata', "gt.tgz")
    resultdata = kwargs.pop('resultdata', "hyp.tgz")
        
    sys.path.append(path.abspath(folder_exec)) # this probably doesnt work on production; dont rely on it
    print("running: " + folder_exec)
    return calc_error_rates(folder_exec,privatedata,resultdata)

def icfhr16_HTR_tool(*args, **kwargs):
    print("icfhr16_HTR_tool")
    executable_folder = '{}/competitions/executables/' \
                        'EvaluationCERandWER'.format(settings.BASE_DIR)
    resultdata = kwargs.pop('resultdata', executable_folder)
    privatedata = kwargs.pop('privatedata',
                             '{}/gt.zip'.format(executable_folder))

    print(resultdata)
    print(privatedata)

    executable = '{}/Create_WER-PAGE.sh'.format(executable_folder)
    commandline = '{} {} {}'.format(executable, resultdata, privatedata)
    print(commandline)

    command_output = cmdline(commandline)

    rgx = r'([\d\.]+)\n+([\d\.]+)'
    r = re.search(rgx, command_output)
    result = {
        'CER': r.group(1),
        'WER': r.group(2),
    }
    print(result)
    return result


def icdar2017_writer_identification(*args, **kwargs):
    print("ICDAR 2017 Writer Identification")
    print(str(kwargs))
    executable_folder = \
        '{}/competitions/executables/ICDAR2017WriterIdentification' \
            .format(settings.BASE_DIR)
    resultdata = kwargs.pop('resultdata', executable_folder)
    privatedata = kwargs.pop('privatedata',
                             '{}/gtfile.txt'.format(executable_folder))

    print(resultdata)
    print(privatedata)

    executable = '{}/evaluation.py'.format(executable_folder)
    commandline = '{} {} {}'.format(executable, privatedata +
                                    '/gtfile.csv', resultdata)
    print(commandline)

    command_output = cmdline(commandline)

    rgx = r'([\d\.]+)\n+([\d\.]+)'
    r = re.search(rgx, command_output)
    result = {
        'WI-precision': r.group(1),
        'WI-map': r.group(2),
    }
    command_output = re.sub(rgx, "", command_output)
    print(result)
    return (result, command_output)


def icdar2017_kws_tool(*args, **kwargs):
    print("==== icdar2017_kws_tool ====")
    executable_folder = \
        '{}/competitions/executables/Icdar17KwsEval'.format(settings.BASE_DIR)
    resultdata = kwargs.pop('resultdata',
                            '{}/QbS_ValidExample.txt'.format(executable_folder))
    privatedata = kwargs.pop('privatedata',
                             '{}/QbS_ValidGT.txt'.format(executable_folder))
    print(resultdata)
    print(privatedata)
    executable = '{}/Icdar17KwsEval'.format(executable_folder)

    if isdir(privatedata):
        gt = '%s/gt.txt' % privatedata
        qset = '%s/keywords.txt' % privatedata
        qgroups = '%s/groups.txt' % privatedata

        if not isfile(gt):
            return None
        elif isfile(qset):
            print('Query-by-String Track')
            commandline = '{} --query_set {} {} {}' \
                .format(executable, qset, gt, resultdata)
        elif isfile(qgroups):
            print('Query-by-Example Track')
            commandline = '{} --query_groups {} {} {}' \
                .format(executable, qgroups, gt, resultdata)
        else:
            commandline = '{} {} {}'.format(executable, gt, resultdata)
    else:
        commandline = '{} {} {}'.format(executable, privatedata, resultdata)

    print(commandline)
    command_output = cmdline(commandline)

    r = re.search(r'gAP = (\S+)', command_output)
    gAP = float(r.group(1)) if r else None

    r = re.search(r'mAP = (\S+)', command_output)
    mAP = float(r.group(1)) if r else None

    result = {'gAP': gAP, 'mAP': mAP}
    print(result)
    return result


def icdar17_BLEU_tool(*args, **kwargs):
    print("icdar17_BLEU_tool")
    executable_folder = '{}/competitions/executables/' \
                        'EvaluationBLEU'.format(settings.BASE_DIR)
    resultdata = kwargs.pop('resultdata', executable_folder)
    privatedata = kwargs.pop('privatedata',
                             '{}/gt.zip'.format(executable_folder))

    print(resultdata)
    print(privatedata)

    executable = '{}/Create_BLEU-PAGE.sh'.format(executable_folder)
    commandline = '{} {} {}'.format(executable, resultdata, privatedata)
    print(commandline)

    command_output = cmdline(commandline)

    print("output of algorithm:")
    print(command_output)
    print("output of algorithm: [DONE]")

    rgx = r'BLEU = ([\d\.]+), .*'

    r = re.search(rgx, command_output)
    result = {
        'BLEU': r.group(1),
    }
    print(result)
    return result

